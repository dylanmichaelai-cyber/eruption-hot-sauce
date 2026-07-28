#!/usr/bin/env python3
"""
YouTube Comments Summary Routine

Fetches recent video comments from a YouTube channel, analyzes them with Claude AI
for sentiment and improvement suggestions, then sends a formatted HTML email digest.

Required environment variables:
  YOUTUBE_API_KEY       — YouTube Data API v3 key (from Google Cloud Console)
  YOUTUBE_CHANNEL_ID    — Your channel ID (e.g. UCxxxx...) OR set YOUTUBE_CHANNEL_HANDLE
  YOUTUBE_CHANNEL_HANDLE — Your channel handle without @ (e.g. "dylanmichaelai"), used if no CHANNEL_ID
  ANTHROPIC_API_KEY     — Anthropic API key for Claude analysis
  EMAIL_FROM            — Gmail address to send from
  GMAIL_APP_PASSWORD    — Gmail App Password (not your account password)
  EMAIL_TO              — Recipient email (defaults to d.mcderm80@gmail.com)
"""

import os
import re
import sys
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import anthropic


YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")
CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
EMAIL_TO = os.environ.get("EMAIL_TO", "d.mcderm80@gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

YT_API = "https://www.googleapis.com/youtube/v3"


def yt_get(endpoint, **params):
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_API}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def resolve_channel_id():
    if CHANNEL_ID:
        return CHANNEL_ID
    if CHANNEL_HANDLE:
        data = yt_get("channels", part="id", forHandle=CHANNEL_HANDLE)
        items = data.get("items", [])
        if not items:
            raise SystemExit(f"No channel found for handle: {CHANNEL_HANDLE}")
        return items[0]["id"]
    raise SystemExit("Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE in environment.")


def get_recent_videos(channel_id, days=30, max_results=10):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = yt_get(
        "search",
        part="snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=max_results,
        publishedAfter=since,
    )
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id, max_results=100):
    try:
        data = yt_get(
            "commentThreads",
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance",
        )
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return []
        raise
    comments = []
    for thread in data.get("items", []):
        top = thread["snippet"]["topLevelComment"]["snippet"]
        comments.append(
            {
                "text": top["textDisplay"],
                "author": top["authorDisplayName"],
                "likes": top.get("likeCount", 0),
                "date": top["publishedAt"][:10],
            }
        )
    return comments


def analyze_with_claude(videos_data):
    lines = []
    for v in videos_data:
        lines.append(f"### {v['title']} (published {v['published']})")
        lines.append(f"URL: https://youtube.com/watch?v={v['id']}")
        if v["comments"]:
            for c in v["comments"][:25]:
                lines.append(f"  [{c['likes']}❤] {c['text'][:250]}")
        else:
            lines.append("  (Comments disabled or none yet)")
        lines.append("")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2500,
        messages=[
            {
                "role": "user",
                "content": f"""You are analyzing YouTube comments for a content creator.
Based on the comments below, write a weekly digest with these exact sections:

**Overall Sentiment**
One paragraph: positive/neutral/negative split, general vibe, energy level.

**What Viewers Love**
Bullet list of 4-6 specific things viewers praise repeatedly.

**Common Criticisms**
Bullet list of 3-5 honest criticisms or complaints that appear more than once.

**Actionable Improvements**
Numbered list of 5-7 concrete, specific things to improve based solely on what viewers said.

**Engagement Patterns**
2-3 sentences on how viewers are engaging (questions asked, topics they expand on, etc.)

**Top Comments Worth Responding To**
List 3 specific comments (quote them exactly) that deserve a reply, with a brief note on why.

Be direct, honest, and specific. Skip generic advice.

---
{chr(10).join(lines)}""",
            }
        ],
    )
    return message.content[0].text


def to_html(md_text):
    html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", md_text)
    html = re.sub(r"^(\d+)\. ", r"<li>", html, flags=re.MULTILINE)
    html = re.sub(r"^- ", r"<li>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.*)", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = html.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"<p>{html}</p>"


def build_html(analysis, videos_data, date_str):
    total = sum(len(v["comments"]) for v in videos_data)
    rows = ""
    for v in videos_data:
        rows += (
            f'<tr><td><a href="https://youtube.com/watch?v={v["id"]}" '
            f'style="color:#c00;text-decoration:none">{v["title"]}</a></td>'
            f'<td style="text-align:center">{len(v["comments"])}</td>'
            f'<td style="text-align:center;color:#888">{v["published"]}</td></tr>'
        )
    analysis_html = to_html(analysis)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f4f4;margin:0;padding:0}}
.wrap{{max-width:680px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
.hdr{{background:linear-gradient(135deg,#c00,#ff4444);color:#fff;padding:32px}}
.hdr h1{{margin:0 0 6px;font-size:26px}}
.hdr p{{margin:0;opacity:.85;font-size:14px}}
.bdy{{padding:32px}}
h2{{color:#c00;font-size:17px;border-bottom:2px solid #ffeeee;padding-bottom:6px;margin-top:28px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#f9f9f9;padding:9px 8px;text-align:left;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.4px}}
td{{padding:9px 8px;border-bottom:1px solid #f0f0f0}}
.analysis{{line-height:1.75;color:#444;font-size:15px}}
.ftr{{background:#f9f9f9;padding:18px 32px;font-size:12px;color:#999;text-align:center}}
</style></head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>🔥 YouTube Comment Digest</h1>
    <p>{date_str} &nbsp;·&nbsp; {len(videos_data)} videos &nbsp;·&nbsp; {total} comments analyzed</p>
  </div>
  <div class="bdy">
    <h2>Videos Analyzed</h2>
    <table>
      <tr><th>Title</th><th style="text-align:center;width:80px">Comments</th><th style="text-align:center;width:100px">Published</th></tr>
      {rows}
    </table>
    <h2>AI Analysis &amp; Insights</h2>
    <div class="analysis">{analysis_html}</div>
  </div>
  <div class="ftr">Generated by your YouTube Comment Routine &nbsp;·&nbsp; Powered by Claude AI</div>
</div>
</body></html>"""


def send_email(subject, html_body, plain_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_FROM, GMAIL_APP_PASSWORD)
        s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print(f"Email sent to {EMAIL_TO}")


def main():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM": EMAIL_FROM,
        "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)
    if not CHANNEL_ID and not CHANNEL_HANDLE:
        print("ERROR: Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE.")
        sys.exit(1)

    print("Resolving channel ID...")
    channel_id = resolve_channel_id()
    print(f"Channel ID: {channel_id}")

    print("Fetching recent videos (last 30 days)...")
    videos = get_recent_videos(channel_id)
    if not videos:
        print("No videos in the last 30 days — nothing to summarize.")
        sys.exit(0)
    print(f"Found {len(videos)} videos.")

    print("Fetching comments...")
    videos_data = []
    for v in videos:
        print(f"  → {v['title'][:55]}...")
        comments = get_comments(v["id"])
        print(f"     {len(comments)} comments")
        videos_data.append({**v, "comments": comments})

    total = sum(len(v["comments"]) for v in videos_data)
    print(f"Analyzing {total} comments with Claude...")
    analysis = analyze_with_claude(videos_data)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    html = build_html(analysis, videos_data, date_str)
    plain = f"YouTube Comment Digest — {date_str}\n\n{analysis}"

    print("Sending email...")
    send_email(f"🔥 YouTube Comment Digest — {date_str}", html, plain)
    print("Done.")


if __name__ == "__main__":
    main()
