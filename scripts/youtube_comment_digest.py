#!/usr/bin/env python3
"""
youtube_comment_digest.py

Fetches recent YouTube comments across your channel's videos,
analyzes sentiment and improvement suggestions via the Claude API,
and emails you a digest.

Required environment variables:
  YOUTUBE_API_KEY     - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID  - Your channel ID (e.g. UCxxxxxxxxxxxxxxxx)
  ANTHROPIC_API_KEY   - Anthropic API key for analysis
  GMAIL_ADDRESS       - Your Gmail address (sender + recipient)
  GMAIL_APP_PASSWORD  - Gmail App Password (not your Google password)
                        Generate one at: https://myaccount.google.com/apppasswords

Optional:
  MAX_VIDEOS          - How many recent videos to scan (default: 5)
  MAX_COMMENTS_PER_VIDEO - Max comments per video (default: 50)

Usage:
  python3 youtube_comment_digest.py

Schedule with cron (weekly on Monday at 8am):
  0 8 * * 1 cd /path/to/repo && python3 scripts/youtube_comment_digest.py
"""

import os
import sys
import json
import smtplib
import textwrap
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def yt_get(endpoint: str, params: dict) -> dict:
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YOUTUBE_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_recent_videos(channel_id: str, max_results: int = 5) -> list[dict]:
    """Return list of {videoId, title, publishedAt} for the most recent uploads."""
    data = yt_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "type": "video",
        "maxResults": max_results,
    })
    videos = []
    for item in data.get("items", []):
        videos.append({
            "videoId": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "publishedAt": item["snippet"]["publishedAt"],
        })
    return videos


def get_comments(video_id: str, max_results: int = 50) -> list[str]:
    """Return a flat list of top-level comment texts for a video."""
    try:
        data = yt_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": min(max_results, 100),
            "textFormat": "plainText",
        })
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return []  # comments disabled
        raise
    comments = []
    for item in data.get("items", []):
        text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        if text.strip():
            comments.append(text.strip())
    return comments


# ---------------------------------------------------------------------------
# Analysis via Claude
# ---------------------------------------------------------------------------

def analyze_comments(video_comments: list[dict]) -> str:
    """
    video_comments: [{title, comments: [str]}, ...]
    Returns a markdown-formatted analysis string.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the input block
    sections = []
    for vc in video_comments:
        if not vc["comments"]:
            continue
        block = f"### {vc['title']}\n"
        block += "\n".join(f"- {c}" for c in vc["comments"][:MAX_COMMENTS_PER_VIDEO])
        sections.append(block)

    if not sections:
        return "No comments were found across the scanned videos."

    comments_text = "\n\n".join(sections)

    prompt = textwrap.dedent(f"""
        You are a YouTube channel analytics assistant. Below are recent viewer comments
        grouped by video for the "Eruption Hot Sauce" YouTube channel.

        Analyse the comments and produce a concise weekly digest with these sections:

        ## Overall Sentiment
        A short paragraph describing how viewers feel overall (positive / negative / mixed),
        with specific quotes as evidence.

        ## What Viewers Love
        Bullet list of the top 3-5 themes that are generating praise or excitement.

        ## Constructive Feedback & Areas to Improve
        Bullet list of the top 3-5 specific, actionable things viewers want improved —
        content gaps, quality issues, requests, complaints, etc.

        ## Quick Wins
        2-3 concrete, low-effort changes you could make in your next video to immediately
        improve audience satisfaction.

        ## Comments by Video
        For each video, one sentence summarising the reaction.

        Keep the tone friendly and encouraging. Use markdown formatting.

        ---
        COMMENTS:
        {comments_text}
    """).strip()

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(subject: str, body_text: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())


def markdown_to_html(md: str) -> str:
    """Minimal markdown → HTML conversion (no extra deps required)."""
    import re
    lines = md.split("\n")
    html_lines = []
    for line in lines:
        # Headings
        if line.startswith("## "):
            line = f"<h2>{line[3:]}</h2>"
        elif line.startswith("### "):
            line = f"<h3>{line[4:]}</h3>"
        # Bullet points
        elif line.startswith("- "):
            line = f"<li>{line[2:]}</li>"
        # Bold
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        # Horizontal rule
        if line.strip() == "---":
            line = "<hr>"
        # Wrap non-tag lines in <p>
        if line and not line.startswith("<"):
            line = f"<p>{line}</p>"
        html_lines.append(line)

    body = "\n".join(html_lines)
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;color:#222;">
{body}
</body></html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    missing = [v for v in ("YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID",
                           "ANTHROPIC_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
               if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("See the module docstring for setup instructions.")
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc).isoformat()}] Fetching recent videos...")
    videos = get_recent_videos(CHANNEL_ID, MAX_VIDEOS)
    if not videos:
        print("No videos found for this channel.")
        sys.exit(0)

    print(f"Found {len(videos)} video(s). Fetching comments...")
    video_comments = []
    for v in videos:
        comments = get_comments(v["videoId"])
        print(f"  {v['title']!r}: {len(comments)} comment(s)")
        video_comments.append({"title": v["title"], "comments": comments})

    print("Analysing with Claude...")
    analysis = analyze_comments(video_comments)

    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject = f"Eruption Hot Sauce — YouTube Comment Digest ({now_str})"
    html = markdown_to_html(analysis)

    print("Sending email...")
    send_email(subject, analysis, html)
    print("Done! Email sent.")


if __name__ == "__main__":
    main()
