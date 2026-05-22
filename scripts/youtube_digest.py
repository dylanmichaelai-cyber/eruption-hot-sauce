#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments across your YouTube videos, analyzes viewer
sentiment and improvement suggestions with Claude, then emails you a
formatted digest.

Usage:
    python youtube_digest.py

Required environment variables (set in scripts/.env):
    YOUTUBE_API_KEY       — YouTube Data API v3 key
    YOUTUBE_CHANNEL_ID    — Your channel ID (starts with UC...)
    ANTHROPIC_API_KEY     — Anthropic API key for Claude analysis
    GMAIL_USER            — Your Gmail address
    GMAIL_APP_PASSWORD    — Gmail App Password (not your login password)
    RECIPIENT_EMAIL       — Where to send the digest (defaults to GMAIL_USER)
"""

import os
import re
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import requests
import anthropic
from dotenv import load_dotenv

# Load .env from the same directory as this script
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

YOUTUBE_API_KEY    = os.environ["YOUTUBE_API_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL    = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)

YT_BASE              = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS           = 10
MAX_COMMENTS_PER_VIDEO = 50


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def get_recent_videos() -> list[dict]:
    resp = requests.get(
        f"{YT_BASE}/search",
        params={
            "key": YOUTUBE_API_KEY,
            "channelId": YOUTUBE_CHANNEL_ID,
            "part": "snippet",
            "order": "date",
            "type": "video",
            "maxResults": MAX_VIDEOS,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
        }
        for item in resp.json().get("items", [])
    ]


def get_comments(video_id: str) -> list[str]:
    comments: list[str] = []
    page_token = None
    while len(comments) < MAX_COMMENTS_PER_VIDEO:
        params = {
            "key": YOUTUBE_API_KEY,
            "videoId": video_id,
            "part": "snippet",
            "order": "relevance",
            "maxResults": min(100, MAX_COMMENTS_PER_VIDEO - len(comments)),
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(f"{YT_BASE}/commentThreads", params=params, timeout=15)
        if resp.status_code == 403:
            # Comments are disabled on this video
            break
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"].strip()
            if text:
                comments.append(text)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return comments


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def analyze_with_claude(videos_with_comments: list[dict]) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    comment_block = ""
    for v in videos_with_comments:
        if not v["comments"]:
            continue
        comment_block += f'\n\n### "{v["title"]}" ({v["published_at"]})\n'
        for c in v["comments"]:
            comment_block += f"- {c}\n"

    if not comment_block.strip():
        return "No comments found across the most recent videos."

    prompt = f"""You are analyzing YouTube comments for a content creator. Below are recent comments from their videos.

{comment_block}

Write a concise, actionable digest structured as follows:

**Overall Sentiment**
A short paragraph on the general mood of the audience.

**What Viewers Love**
Bullet points of recurring praise and things that are landing well.

**Areas for Improvement**
Actionable bullet points drawn directly from viewer feedback and criticism.

**Viewer Requests & Trending Topics**
Topics, formats, or video ideas the audience is asking for.

**Notable Comments**
2–3 standout comments worth the creator's attention (quote them verbatim).

Keep the tone honest and constructive — the goal is to help the creator grow."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """Lightweight Markdown → HTML for the email body."""
    html: list[str] = []
    in_list = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            if in_list: html.append("</ul>"); in_list = False
            html.append(f"<h4>{stripped[4:]}</h4>")
        elif stripped.startswith("**") and stripped.endswith("**"):
            if in_list: html.append("</ul>"); in_list = False
            html.append(f"<h4 style='margin-top:18px;margin-bottom:6px;'>{stripped[2:-2]}</h4>")
        elif stripped.startswith("- "):
            if not in_list: html.append("<ul>"); in_list = True
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", stripped[2:])
            html.append(f"<li>{content}</li>")
        elif stripped == "":
            if in_list: html.append("</ul>"); in_list = False
        else:
            if in_list: html.append("</ul>"); in_list = False
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", stripped)
            html.append(f"<p>{content}</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def send_digest(subject: str, plain_body: str, videos_with_comments: list[dict]):
    today = datetime.now().strftime("%B %d, %Y")
    total_comments = sum(len(v["comments"]) for v in videos_with_comments)

    html_body = f"""
<html>
<body style="font-family:Georgia,serif;max-width:680px;margin:auto;padding:28px;color:#222;">
  <h2 style="color:#c0392b;margin-bottom:4px;">YouTube Comment Digest</h2>
  <p style="color:#888;font-size:13px;margin-top:0;">
    {today} &nbsp;·&nbsp; {len(videos_with_comments)} videos &nbsp;·&nbsp;
    {total_comments} comments analyzed
  </p>
  <hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">
  {_md_to_html(plain_body)}
  <hr style="border:none;border-top:1px solid #ddd;margin:24px 0 12px;">
  <p style="color:#aaa;font-size:11px;">
    Sent by your YouTube Comment Digest routine. Run <code>python youtube_digest.py</code> any time to refresh.
  </p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Fetching recent videos...")
    try:
        videos = get_recent_videos()
    except requests.HTTPError as e:
        sys.exit(f"YouTube API error fetching videos: {e}")

    if not videos:
        sys.exit("No videos found for this channel ID.")

    print(f"Found {len(videos)} video(s). Fetching comments...")
    videos_with_comments: list[dict] = []
    for v in videos:
        comments = get_comments(v["video_id"])
        print(f"  [{v['published_at']}] {v['title']!r}: {len(comments)} comment(s)")
        videos_with_comments.append({**v, "comments": comments})

    print("Analyzing with Claude...")
    digest = analyze_with_claude(videos_with_comments)

    today = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Comment Digest — {today}"

    print(f"Sending digest to {RECIPIENT_EMAIL}...")
    send_digest(subject, digest, videos_with_comments)
    print("Done! Check your inbox.")


if __name__ == "__main__":
    main()
