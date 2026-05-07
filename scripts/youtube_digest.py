#!/usr/bin/env python3
"""
YouTube Comment Digest
----------------------
Fetches comments from your recent YouTube videos, analyzes them with Claude
for sentiment and improvement suggestions, then emails you an HTML summary.

Schedule with cron (weekly on Monday at 9am):
    0 9 * * 1 cd /path/to/eruption-hot-sauce && python scripts/youtube_digest.py

Required env vars (see scripts/.env.example):
    YOUTUBE_API_KEY, ANTHROPIC_API_KEY, YOUTUBE_CHANNEL_ID,
    SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL
"""

import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "100"))

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def get_recent_videos(channel_id: str, max_results: int = 5):
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/channels",
        params={"part": "contentDetails,snippet", "id": channel_id, "key": YOUTUBE_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("items"):
        raise ValueError(f"Channel '{channel_id}' not found. Check YOUTUBE_CHANNEL_ID.")

    channel = data["items"][0]
    channel_title = channel["snippet"]["title"]
    uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    resp = requests.get(
        f"{YOUTUBE_API_BASE}/playlistItems",
        params={
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()

    videos = [
        {
            "id": item["contentDetails"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
        }
        for item in resp.json().get("items", [])
    ]
    return channel_title, videos


def get_video_comments(video_id: str, max_results: int = 100) -> list[dict]:
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/commentThreads",
        params={
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(max_results, 100),
            "order": "relevance",
            "key": YOUTUBE_API_KEY,
        },
        timeout=15,
    )
    if resp.status_code == 403:
        return []  # comments disabled on this video
    resp.raise_for_status()

    comments = []
    for item in resp.json().get("items", []):
        s = item["snippet"]["topLevelComment"]["snippet"]
        comments.append(
            {
                "text": s["textDisplay"],
                "author": s["authorDisplayName"],
                "likes": s["likeCount"],
                "published_at": s["publishedAt"],
            }
        )
    return comments


def analyze_with_claude(channel_title: str, videos_with_comments: list[dict]) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt_parts = [f"# YouTube Channel: {channel_title}\n"]
    prompt_parts.append(
        f"Analyze comments from the {len(videos_with_comments)} most recent videos:\n"
    )

    for video in videos_with_comments:
        prompt_parts.append(f"\n## Video: {video['title']}")
        prompt_parts.append(f"URL: https://youtube.com/watch?v={video['id']}")
        prompt_parts.append(f"Comment count: {len(video['comments'])}\n")
        for c in video["comments"][:50]:
            likes = f"[{c['likes']} likes] " if c["likes"] else ""
            prompt_parts.append(f"- {likes}{c['text'][:250]}")

    prompt_parts.append(
        """
Please analyze these comments and return a complete HTML fragment (no <html>/<body> wrappers,
inline styles only) covering these sections:

1. **Overall Sentiment** — positive/neutral/negative rough percentages and a one-sentence vibe check
2. **What People Love** — 3-5 specific things viewers consistently praise
3. **Top Improvement Areas** — 3-5 actionable suggestions backed by viewer feedback
4. **Recurring Themes & Requests** — patterns, topics, or questions that come up repeatedly
5. **Standout Comments** — 2-3 quoted comments that are especially insightful or representative
6. **Your Action Items** — 3 concrete next steps to act on this week

Use a warm, professional tone. Style with inline CSS; use a color palette of deep red (#c0392b)
and charcoal (#2c3e50) to match a hot-sauce brand. Make it look great in an email client."""
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
    )
    return message.content[0].text


def build_email_html(channel_title: str, analysis_html: str) -> str:
    now = datetime.now().strftime("%B %d, %Y")
    return f"""
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:30px 0;">
  <tr><td align="center">
    <table width="660" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;">
      <tr>
        <td style="background:linear-gradient(135deg,#c0392b,#e74c3c);padding:28px 36px;">
          <h1 style="margin:0;color:#ffffff;font-size:24px;letter-spacing:-0.5px;">
            🌶 YouTube Comment Digest
          </h1>
          <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">
            {channel_title} &nbsp;·&nbsp; {now}
          </p>
        </td>
      </tr>
      <tr>
        <td style="padding:30px 36px;">
          {analysis_html}
        </td>
      </tr>
      <tr>
        <td style="padding:16px 36px;border-top:1px solid #eee;background:#fafafa;">
          <p style="margin:0;color:#aaa;font-size:12px;text-align:center;">
            Auto-generated by your YouTube Digest script &nbsp;·&nbsp; Powered by Claude
          </p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>
"""


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, RECIPIENT_EMAIL, msg.as_string())


def main() -> None:
    print(f"[{datetime.now().isoformat()}] YouTube Comment Digest starting…")

    missing = [
        k
        for k, v in {
            "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
            "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
            "YOUTUBE_CHANNEL_ID": YOUTUBE_CHANNEL_ID,
            "SMTP_USER": SMTP_USER,
            "SMTP_PASSWORD": SMTP_PASSWORD,
            "RECIPIENT_EMAIL": RECIPIENT_EMAIL,
        }.items()
        if not v
    ]
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        print("Copy scripts/.env.example to scripts/.env and fill in the values.")
        sys.exit(1)

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {YOUTUBE_CHANNEL_ID}…")
    channel_title, videos = get_recent_videos(YOUTUBE_CHANNEL_ID, max_results=MAX_VIDEOS)
    print(f"Channel: {channel_title}  |  Videos found: {len(videos)}")

    videos_with_comments = []
    for video in videos:
        print(f"  → {video['title'][:70]}")
        comments = get_video_comments(video["id"], max_results=MAX_COMMENTS_PER_VIDEO)
        print(f"      {len(comments)} comments")
        videos_with_comments.append({**video, "comments": comments})

    total = sum(len(v["comments"]) for v in videos_with_comments)
    if total == 0:
        print("No comments found across any videos. Exiting without sending email.")
        return

    print(f"\nAnalyzing {total} comments with Claude…")
    analysis_html = analyze_with_claude(channel_title, videos_with_comments)

    subject = f"YouTube Digest: {channel_title} — {datetime.now().strftime('%b %d, %Y')}"
    html_body = build_email_html(channel_title, analysis_html)

    print(f"Sending digest to {RECIPIENT_EMAIL}…")
    send_email(subject, html_body)

    print("Done! Email sent successfully.")


if __name__ == "__main__":
    main()
