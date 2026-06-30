#!/usr/bin/env python3
"""
YouTube Comment Digest — fetches recent comments from a YouTube channel,
analyzes sentiment via Claude, and emails a summary via Gmail SMTP.

Required env vars:
  YOUTUBE_API_KEY   — YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID — Your YouTube channel ID (e.g. UCxxxxxxxx...)
  GMAIL_ADDRESS     — Gmail address to send FROM and TO (d.mcderm80@gmail.com)
  GMAIL_APP_PASSWORD — Gmail App Password (not your account password)
                       Generate at: https://myaccount.google.com/apppasswords
  ANTHROPIC_API_KEY — Claude API key for sentiment analysis
"""

import os
import sys
import json
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

YT_API_KEY = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]


def yt_get(endpoint, params):
    params["key"] = YT_API_KEY
    url = f"{YOUTUBE_API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def fetch_recent_videos(channel_id, max_results=10):
    data = yt_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "maxResults": max_results,
    })
    return [
        {"id": item["id"]["videoId"], "title": item["snippet"]["title"]}
        for item in data.get("items", [])
    ]


def fetch_comments(video_id, max_results=50):
    try:
        data = yt_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "relevance",
        })
        return [
            item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            for item in data.get("items", [])
        ]
    except Exception as e:
        print(f"  Warning: could not fetch comments for {video_id}: {e}")
        return []


def analyze_with_claude(videos_and_comments):
    prompt_lines = []
    total_comments = 0
    for video in videos_and_comments:
        prompt_lines.append(f"\n### Video: {video['title']}")
        for c in video["comments"]:
            prompt_lines.append(f"- {c}")
            total_comments += 1

    comments_block = "\n".join(prompt_lines)

    prompt = f"""You are analyzing YouTube comments for a hot sauce channel called "Eruption Hot Sauce".

Below are comments from the {len(videos_and_comments)} most recent videos ({total_comments} comments total).
Produce a structured analysis in HTML format with these sections:

1. <h2>Overall Sentiment</h2> — breakdown of positive / neutral / negative (rough percentages)
2. <h2>What Viewers Love</h2> — top 4-5 things praised most (bullet list)
3. <h2>Areas to Improve</h2> — top 4-5 criticisms or recurring suggestions (bullet list)
4. <h2>Actionable Ideas</h2> — specific, concrete suggestions mentioned by viewers (bullet list)
5. <h2>Standout Comments</h2> — 4-5 particularly insightful comments, quoted verbatim in <blockquote> tags
6. <h2>Video-by-Video Notes</h2> — one-sentence sentiment summary per video analyzed

Use clean, readable HTML. Do not include <html>, <head>, or <body> tags — just the inner content.

--- COMMENTS ---
{comments_block}
"""

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    return resp["content"][0]["text"]


def build_html_email(analysis_html, video_count, comment_count, run_date):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #222; }}
  h1 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 8px; }}
  h2 {{ color: #e74c3c; margin-top: 28px; }}
  blockquote {{ background: #f9f9f9; border-left: 4px solid #c0392b; margin: 8px 0; padding: 8px 16px; }}
  .meta {{ color: #777; font-size: 13px; margin-bottom: 24px; }}
  ul {{ line-height: 1.8; }}
</style>
</head>
<body>
<h1>🌶️ Eruption Hot Sauce — YouTube Comment Digest</h1>
<p class="meta">
  Generated: {run_date} &nbsp;|&nbsp;
  Videos analyzed: {video_count} &nbsp;|&nbsp;
  Comments analyzed: {comment_count}
</p>
{analysis_html}
<hr style="margin-top:40px">
<p style="color:#aaa;font-size:12px">
  This digest is auto-generated weekly. To adjust the schedule or channel,
  update the GitHub Actions workflow at .github/workflows/youtube_digest.yml.
</p>
</body>
</html>"""


def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())


def main():
    run_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_label = datetime.now(timezone.utc).strftime("Week of %b %d, %Y")

    print(f"Fetching recent videos from channel {CHANNEL_ID}...")
    videos = fetch_recent_videos(CHANNEL_ID, max_results=10)
    if not videos:
        print("No videos found. Check your YOUTUBE_CHANNEL_ID.")
        sys.exit(1)
    print(f"Found {len(videos)} videos.")

    videos_and_comments = []
    total_comments = 0
    for v in videos:
        print(f"  Fetching comments for: {v['title'][:60]}...")
        comments = fetch_comments(v["id"], max_results=50)
        videos_and_comments.append({**v, "comments": comments})
        total_comments += len(comments)

    print(f"Collected {total_comments} comments. Analyzing with Claude...")
    analysis_html = analyze_with_claude(videos_and_comments)

    html_body = build_html_email(analysis_html, len(videos), total_comments, run_date)
    subject = f"🌶️ Eruption Hot Sauce YouTube Digest — {week_label}"

    print(f"Sending email to {GMAIL_ADDRESS}...")
    send_email(subject, html_body)
    print("Done! Email sent.")


if __name__ == "__main__":
    main()
