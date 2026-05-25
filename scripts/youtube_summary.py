#!/usr/bin/env python3
"""
YouTube Comment Summary
Fetches recent comments from your YouTube channel, analyzes sentiment
and improvement areas with Claude, then emails you a formatted report.

Required environment variables:
  YOUTUBE_API_KEY       - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID    - Your channel ID (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)
  ANTHROPIC_API_KEY     - Anthropic API key for Claude
  GMAIL_ADDRESS         - Your Gmail address (sender + recipient)
  GMAIL_APP_PASSWORD    - Gmail App Password (not your login password)
                          Generate one at: https://myaccount.google.com/apppasswords

Optional:
  REPORT_EMAIL          - Override recipient email (defaults to GMAIL_ADDRESS)
  MAX_VIDEOS            - Number of recent videos to scan (default: 5)
  MAX_COMMENTS_PER_VIDEO- Comments per video to fetch (default: 50)
"""

import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Configuration ──────────────────────────────────────────────────────────────
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
REPORT_EMAIL = os.getenv("REPORT_EMAIL", "") or GMAIL_ADDRESS

MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "50"))

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
# ───────────────────────────────────────────────────────────────────────────────


def get_channel_videos(channel_id: str) -> list[dict]:
    params = {
        "key": YOUTUBE_API_KEY,
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "maxResults": MAX_VIDEOS,
        "type": "video",
    }
    resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
        }
        for item in items
    ]


def get_video_comments(video_id: str) -> list[dict]:
    params = {
        "key": YOUTUBE_API_KEY,
        "videoId": video_id,
        "part": "snippet",
        "maxResults": MAX_COMMENTS_PER_VIDEO,
        "order": "relevance",
        "textFormat": "plainText",
    }
    resp = requests.get(YOUTUBE_COMMENTS_URL, params=params, timeout=15)
    if resp.status_code == 403:
        return []
    resp.raise_for_status()
    comments = []
    for item in resp.json().get("items", []):
        s = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "author": s["authorDisplayName"],
            "text": s["textDisplay"],
            "likes": s["likeCount"],
        })
    return comments


def analyze_with_claude(videos_with_comments: list[dict]) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    sections = []
    total_comments = 0
    for v in videos_with_comments:
        if not v["comments"]:
            continue
        section = f"### {v['title']} ({v['published_at']})\n"
        for c in v["comments"]:
            like_str = f"[{c['likes']} ♥] " if c["likes"] else ""
            section += f"- {like_str}{c['text']}\n"
            total_comments += 1
        sections.append(section)

    if total_comments == 0:
        return "No comments were found across the selected videos."

    comments_block = "\n".join(sections)
    prompt = f"""You are a YouTube channel strategist reviewing audience comments for "Eruption Hot Sauce," a hot sauce brand channel.

Below are {total_comments} comments pulled from the {len(sections)} most recent video(s):

{comments_block}

Write a concise, actionable report with these sections:

**Overall Sentiment** — One paragraph on the general audience mood (positive/neutral/negative ratio and why).

**What Viewers Love** — Bullet list of 3–5 things viewers consistently praise.

**Concerns & Criticisms** — Bullet list of recurring complaints or constructive feedback (be specific).

**Top Improvement Recommendations** — Numbered list of 4–6 concrete actions the channel owner can take based on this feedback.

**Standout Comments** — Quote 2–3 high-signal comments (positive or critical) worth reading verbatim.

Keep the tone direct, specific, and useful. Avoid generic advice."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_html(report_text: str, videos: list[dict], date_str: str) -> str:
    video_rows = "".join(
        f'<tr><td><a href="{v["url"]}" style="color:#e25c00">{v["title"]}</a></td>'
        f'<td style="padding-left:12px;color:#888">{v["published_at"]}</td></tr>'
        for v in videos
    )

    # Convert basic markdown to HTML
    html_report = report_text
    import re
    html_report = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_report)
    html_report = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_report)
    # Section headers
    html_report = re.sub(r'^#{1,3} (.+)$', r'<h3 style="color:#c94e00;margin-top:24px">\1</h3>', html_report, flags=re.MULTILINE)
    # Bullet lists
    lines = html_report.split("\n")
    in_list = False
    out_lines = []
    for line in lines:
        if re.match(r'^[-•]\s', line):
            if not in_list:
                out_lines.append("<ul>")
                in_list = True
            out_lines.append(f"<li>{line[2:].strip()}</li>")
        elif re.match(r'^\d+\.\s', line):
            if not in_list:
                out_lines.append("<ol>")
                in_list = True
            out_lines.append(f"<li>{re.sub(r'^\d+\.\s', '', line).strip()}</li>")
        else:
            if in_list:
                out_lines.append("</ul>")
                in_list = False
            out_lines.append(line if line.strip() else "<br>")
    if in_list:
        out_lines.append("</ul>")
    html_report = "\n".join(out_lines)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Georgia,serif;max-width:680px;margin:40px auto;padding:0 20px;color:#222;line-height:1.6">
  <div style="background:#c94e00;padding:20px 28px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;color:#fff;font-size:22px">🌋 Eruption Hot Sauce</h1>
    <p style="margin:4px 0 0;color:#ffd8c0;font-size:14px">YouTube Comment Analysis — {date_str}</p>
  </div>
  <div style="border:1px solid #eee;border-top:none;padding:24px 28px;border-radius:0 0 8px 8px">
    <h2 style="font-size:16px;color:#555;font-weight:normal;margin-top:0">
      Videos analyzed ({len(videos)}):
    </h2>
    <table style="font-size:14px;margin-bottom:24px">{video_rows}</table>
    <hr style="border:none;border-top:2px solid #f0e0d8;margin:20px 0">
    {html_report}
    <hr style="border:none;border-top:1px solid #eee;margin:32px 0 16px">
    <p style="font-size:12px;color:#aaa;margin:0">
      Generated automatically by your YouTube Comment Summary routine.
    </p>
  </div>
</body>
</html>"""


def send_email(subject: str, plain_body: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = REPORT_EMAIL
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, REPORT_EMAIL, msg.as_string())


def check_config() -> None:
    missing = []
    if not CHANNEL_ID:
        missing.append("YOUTUBE_CHANNEL_ID")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not GMAIL_ADDRESS:
        missing.append("GMAIL_ADDRESS")
    if not GMAIL_APP_PASSWORD:
        missing.append("GMAIL_APP_PASSWORD")
    if missing:
        print("ERROR: Missing required environment variables:")
        for v in missing:
            print(f"  {v}")
        print("\nSee the script header for setup instructions.")
        sys.exit(1)


def main() -> None:
    check_config()

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {CHANNEL_ID}...")
    videos = get_channel_videos(CHANNEL_ID)
    if not videos:
        print("No videos found. Check your YOUTUBE_CHANNEL_ID.")
        sys.exit(1)
    print(f"Found {len(videos)} video(s).")

    videos_with_comments = []
    for v in videos:
        print(f"  → {v['title']}")
        comments = get_video_comments(v["id"])
        print(f"     {len(comments)} comment(s) fetched.")
        videos_with_comments.append({**v, "comments": comments})

    print("Analyzing with Claude...")
    analysis = analyze_with_claude(videos_with_comments)

    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Comment Summary — {date_str}"

    video_list = "\n".join(f"  • {v['title']} ({v['published_at']})" for v in videos)
    plain_body = (
        f"YouTube Comment Analysis Report\n"
        f"Generated: {date_str}\n\n"
        f"Videos analyzed:\n{video_list}\n\n"
        f"{'─' * 60}\n\n"
        f"{analysis}\n\n"
        f"{'─' * 60}\n"
        f"Generated automatically by your YouTube Comment Summary routine.\n"
    )
    html_body = build_html(analysis, videos, date_str)

    print(f"Sending summary to {REPORT_EMAIL}...")
    send_email(subject, plain_body, html_body)
    print("Done — email sent successfully.")


if __name__ == "__main__":
    main()
