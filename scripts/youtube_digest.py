#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches comments from your recent YouTube videos and emails a sentiment
analysis + improvement suggestions via Gmail SMTP (App Password).

Required environment variables:
  YOUTUBE_API_KEY       — YouTube Data API v3 key (from Google Cloud Console)
  YOUTUBE_CHANNEL_ID    — Your channel ID (e.g. UCxxxxxxxxxxxxxxxxxx)
  ANTHROPIC_API_KEY     — Anthropic API key for comment analysis
  GMAIL_USER            — Your Gmail address (e.g. you@gmail.com)
  GMAIL_APP_PASSWORD    — Gmail App Password (not your regular password)
  RECIPIENT_EMAIL       — Where to send the digest (defaults to GMAIL_USER)
"""

import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)

VIDEOS_TO_CHECK = 5
COMMENTS_PER_VIDEO = 100


def get_recent_videos(channel_id: str, api_key: str) -> list[dict]:
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": VIDEOS_TO_CHECK,
            "key": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def get_video_comments(video_id: str, api_key: str) -> list[str]:
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/commentThreads",
        params={
            "part": "snippet",
            "videoId": video_id,
            "maxResults": COMMENTS_PER_VIDEO,
            "order": "relevance",
            "key": api_key,
        },
        timeout=15,
    )
    if resp.status_code == 403:
        return []  # comments disabled on this video
    resp.raise_for_status()
    return [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in resp.json().get("items", [])
    ]


def analyze_comments(comments_by_video: dict[str, list[str]]) -> str:
    sections = []
    for title, comments in comments_by_video.items():
        bullet_list = "\n".join(f"  - {c[:300]}" for c in comments[:50])
        sections.append(f"### {title}\n{bullet_list}")

    prompt = f"""You are analyzing YouTube comments for a hot sauce brand called Eruption Hot Sauce.
Review the following comments from {len(comments_by_video)} recent videos and provide a concise digest.

{chr(10).join(sections)}

Return ONLY valid HTML (no markdown fences) with these sections:
1. <h2>Overall Sentiment</h2> — percentage breakdown (positive / neutral / negative) with 2-sentence summary
2. <h2>What Viewers Love</h2> — top 3–5 recurring praise themes as <ul><li> list
3. <h2>Common Complaints & Concerns</h2> — top 3–5 issues as <ul><li> list
4. <h2>Actionable Improvements</h2> — 3–5 specific, prioritized steps as <ol><li> list
5. <h2>Notable Comments</h2> — 3 standout quotes in <blockquote> tags

Be specific, concise, and directly useful."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-opus-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())


def main() -> None:
    print(f"Fetching videos for channel {CHANNEL_ID}...")
    videos = get_recent_videos(CHANNEL_ID, YOUTUBE_API_KEY)

    if not videos:
        print("No videos found. Check YOUTUBE_CHANNEL_ID.")
        sys.exit(1)

    comments_by_video: dict[str, list[str]] = {}
    for video in videos:
        video_id = video["id"]["videoId"]
        title = video["snippet"]["title"]
        print(f"  Fetching comments for: {title}")
        comments = get_video_comments(video_id, YOUTUBE_API_KEY)
        if comments:
            comments_by_video[title] = comments

    total = sum(len(c) for c in comments_by_video.values())
    print(f"Analyzing {total} comments across {len(comments_by_video)} videos...")

    if not comments_by_video:
        print("No comments found across any video.")
        sys.exit(0)

    analysis_html = analyze_comments(comments_by_video)

    date_str = datetime.now().strftime("%b %d, %Y")
    subject = f"Eruption Hot Sauce — YouTube Digest ({date_str}, {total} comments)"

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; color: #222; }}
    h1 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 8px; }}
    h2 {{ color: #c0392b; margin-top: 28px; }}
    blockquote {{ border-left: 4px solid #c0392b; margin: 12px 0; padding: 8px 16px; background: #fdf2f2; color: #555; font-style: italic; }}
    ul, ol {{ padding-left: 20px; }}
    li {{ margin-bottom: 6px; line-height: 1.5; }}
    .meta {{ background: #fdf2f2; padding: 12px; border-radius: 6px; margin-bottom: 20px; font-size: 14px; }}
    .footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid #eee; color: #999; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Eruption Hot Sauce — YouTube Comment Digest</h1>
  <div class="meta">
    <strong>Date:</strong> {date_str} &nbsp;|&nbsp;
    <strong>Videos analyzed:</strong> {len(comments_by_video)} &nbsp;|&nbsp;
    <strong>Total comments:</strong> {total}
  </div>
  {analysis_html}
  <div class="footer">
    Generated automatically by the YouTube Comment Digest routine.<br>
    Videos analyzed: {', '.join(comments_by_video.keys())}
  </div>
</body>
</html>"""

    print(f"Sending digest to {RECIPIENT_EMAIL}...")
    send_email(subject, html_body)
    print("Done.")


if __name__ == "__main__":
    main()
