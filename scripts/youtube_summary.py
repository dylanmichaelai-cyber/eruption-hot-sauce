#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches comments from your YouTube channel, analyzes sentiment with Claude,
and emails you a summary of what viewers think and what you can improve.

Usage:
    python youtube_summary.py

Required environment variables (see .env.example):
    YOUTUBE_CHANNEL_ID   — Your YouTube channel ID
    ANTHROPIC_API_KEY    — Your Anthropic API key
    SMTP_USER            — Gmail address to send from
    SMTP_PASSWORD        — Gmail App Password (not your account password)
    SUMMARY_EMAIL        — Email address to receive the summary (defaults to SMTP_USER)

Optional:
    YOUTUBE_API_KEY      — Overrides the default key
    SMTP_HOST            — SMTP host (default: smtp.gmail.com)
    SMTP_PORT            — SMTP port (default: 587)
    MAX_VIDEOS           — Recent videos to analyze (default: 5)
    MAX_COMMENTS         — Comments per video (default: 50)
"""

import os
import re
import sys
import smtplib
import argparse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
DEFAULT_YOUTUBE_API_KEY = "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c"


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------

def get_channel_videos(api_key: str, channel_id: str, max_videos: int = 5) -> list[dict]:
    """Fetch the most recent videos from a YouTube channel."""
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/search",
        params={
            "key": api_key,
            "channelId": channel_id,
            "part": "snippet",
            "order": "date",
            "type": "video",
            "maxResults": min(max_videos, 50),
        },
        timeout=15,
    )
    resp.raise_for_status()
    videos = []
    for item in resp.json().get("items", []):
        videos.append({
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
        })
    return videos


def get_video_comments(api_key: str, video_id: str, max_comments: int = 50) -> list[dict]:
    """Fetch top-level comments for a single YouTube video, sorted by relevance."""
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/commentThreads",
        params={
            "key": api_key,
            "videoId": video_id,
            "part": "snippet",
            "maxResults": min(max_comments, 100),
            "order": "relevance",
            "textFormat": "plainText",
        },
        timeout=15,
    )
    resp.raise_for_status()
    comments = []
    for item in resp.json().get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "author": top["authorDisplayName"],
            "text": top["textDisplay"].strip(),
            "likes": top["likeCount"],
        })
    return comments


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_with_claude(client: anthropic.Anthropic, videos: list[dict]) -> str:
    """Send comments to Claude and get a structured sentiment + improvement report."""
    lines = []
    for v in videos:
        lines.append(f"\n### Video: \"{v['title']}\" (published {v['published_at']})")
        if not v["comments"]:
            lines.append("(No comments available for this video)")
            continue
        for c in v["comments"][:40]:  # cap per video to stay within context
            likes = f"+{c['likes']}" if c["likes"] else ""
            lines.append(f"- {likes} {c['text']}")

    comments_block = "\n".join(lines)

    prompt = f"""You are a helpful analyst for a YouTube content creator.
Review the comments below and produce a concise, actionable report with these five sections:

1. **Overall Sentiment** — How do viewers generally feel? (positive / mixed / negative, key emotions)
2. **What's Working** — Specific aspects viewers praise or react positively to
3. **Areas to Improve** — Concrete, actionable suggestions directly grounded in viewer feedback
4. **Top Viewer Requests** — Content, features, or changes viewers explicitly ask for
5. **Quick Wins** — 2–3 easy changes that could noticeably boost viewer satisfaction

Be specific and quote or paraphrase real comments where it strengthens a point. Keep the total report under 600 words.

---

{comments_block}
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """Minimal markdown-to-HTML conversion for the report."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?m)^#{1,3}\s+(.*)', r'<h3>\1</h3>', text)
    text = re.sub(r'(?m)^[-*]\s+(.*)', r'<li>\1</li>', text)
    text = re.sub(r'((?:<li>.*</li>\n?)+)', r'<ul>\1</ul>', text)
    paragraphs = [f"<p>{p.strip()}</p>" for p in text.split("\n\n") if p.strip()]
    return "\n".join(paragraphs)


def build_html_email(analysis: str, videos: list[dict], generated_at: str) -> str:
    video_rows = "".join(
        f'<tr><td><a href="https://youtube.com/watch?v={v["id"]}">{v["title"]}</a></td>'
        f'<td>{v["published_at"]}</td><td>{len(v["comments"])} comments</td></tr>'
        for v in videos
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; max-width: 680px; margin: 0 auto; color: #222; line-height: 1.6; }}
  h1   {{ background: #c0392b; color: #fff; padding: 16px 20px; border-radius: 6px; margin: 0 0 20px; }}
  h2   {{ color: #c0392b; border-bottom: 2px solid #e74c3c; padding-bottom: 4px; }}
  h3   {{ color: #b03a2e; margin: 14px 0 4px; }}
  .meta {{ color: #888; font-size: .85em; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
  th    {{ background: #f2f2f2; text-align: left; padding: 8px; }}
  td    {{ padding: 8px; border-bottom: 1px solid #eee; }}
  .analysis {{ background: #fafafa; border-left: 4px solid #e74c3c; padding: 16px 20px; border-radius: 0 6px 6px 0; }}
  ul    {{ padding-left: 20px; }}
  li    {{ margin-bottom: 4px; }}
  a     {{ color: #c0392b; }}
</style>
</head>
<body>
  <h1>YouTube Comment Summary</h1>
  <p class="meta">Generated {generated_at}</p>

  <h2>Videos Analyzed</h2>
  <table>
    <tr><th>Title</th><th>Published</th><th>Comments</th></tr>
    {video_rows}
  </table>

  <h2>Analysis</h2>
  <div class="analysis">
    {_md_to_html(analysis)}
  </div>
</body>
</html>"""


def send_email(
    host: str, port: int,
    username: str, password: str,
    to_addr: str, subject: str,
    html_body: str, text_body: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_addr
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(username, password)
            server.sendmail(username, to_addr, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(username, password)
            server.sendmail(username, to_addr, msg.as_string())

    print(f"  Email delivered to {to_addr}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube Comment Summary Emailer")
    parser.add_argument("--channel-id",   default=os.environ.get("YOUTUBE_CHANNEL_ID"))
    parser.add_argument("--max-videos",   type=int, default=int(os.environ.get("MAX_VIDEOS", 5)))
    parser.add_argument("--max-comments", type=int, default=int(os.environ.get("MAX_COMMENTS", 50)))
    args = parser.parse_args()

    yt_api_key     = os.environ.get("YOUTUBE_API_KEY", DEFAULT_YOUTUBE_API_KEY)
    anthropic_key  = os.environ.get("ANTHROPIC_API_KEY")
    channel_id     = args.channel_id
    smtp_host      = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port      = int(os.environ.get("SMTP_PORT", 587))
    smtp_user      = os.environ.get("SMTP_USER")
    smtp_pass      = os.environ.get("SMTP_PASSWORD")
    to_email       = os.environ.get("SUMMARY_EMAIL") or smtp_user

    errors = []
    if not channel_id:
        errors.append("YOUTUBE_CHANNEL_ID — find it in YouTube Studio > Settings > Channel > Advanced settings")
    if not anthropic_key:
        errors.append("ANTHROPIC_API_KEY — get it from console.anthropic.com")
    if not smtp_user:
        errors.append("SMTP_USER — your Gmail address")
    if not smtp_pass:
        errors.append("SMTP_PASSWORD — your Gmail App Password (myaccount.google.com/apppasswords)")
    if errors:
        print("Missing required configuration:\n" + "\n".join(f"  - {e}" for e in errors))
        print("\nSet these as environment variables or add them to a .env file (see .env.example).")
        return 1

    print(f"[1/4] Fetching up to {args.max_videos} recent videos from channel {channel_id}...")
    try:
        videos = get_channel_videos(yt_api_key, channel_id, args.max_videos)
    except requests.HTTPError as e:
        print(f"YouTube API error: {e.response.status_code} — {e.response.text}")
        return 1

    if not videos:
        print("No videos found for this channel.")
        return 0

    print(f"[2/4] Fetching comments for {len(videos)} video(s)...")
    videos_with_comments = []
    for v in videos:
        try:
            comments = get_video_comments(yt_api_key, v["id"], args.max_comments)
            print(f"  \"{v['title'][:60]}\" — {len(comments)} comments")
        except requests.HTTPError as e:
            print(f"  Warning: could not fetch comments for {v['id']}: {e.response.status_code}")
            comments = []
        videos_with_comments.append({**v, "comments": comments})

    print("[3/4] Analyzing comments with Claude...")
    client = anthropic.Anthropic(api_key=anthropic_key)
    analysis = analyze_with_claude(client, videos_with_comments)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"YouTube Comment Summary — {generated_at}"
    html_body = build_html_email(analysis, videos_with_comments, generated_at)

    print(f"[4/4] Sending summary email to {to_email}...")
    try:
        send_email(smtp_host, smtp_port, smtp_user, smtp_pass, to_email, subject, html_body, analysis)
    except smtplib.SMTPAuthenticationError:
        print("SMTP authentication failed. Make sure you're using a Gmail App Password, not your account password.")
        print("Create one at: https://myaccount.google.com/apppasswords")
        return 1
    except Exception as e:
        print(f"Failed to send email: {e}")
        return 1

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
