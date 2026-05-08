#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches recent video comments from your YouTube channel, analyzes sentiment
and improvement opportunities using Claude, then emails you the report.

Usage:
    python3 youtube_summary.py

Required env vars (see .env.example):
    YOUTUBE_API_KEY, YOUTUBE_CHANNEL_ID, ANTHROPIC_API_KEY,
    EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD
"""

import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY       = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID    = os.getenv("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
EMAIL_FROM            = os.getenv("EMAIL_FROM", "")
EMAIL_TO              = os.getenv("EMAIL_TO", "")
EMAIL_APP_PASSWORD    = os.getenv("EMAIL_APP_PASSWORD", "")
MAX_VIDEOS            = int(os.getenv("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "50"))

YT_BASE = "https://www.googleapis.com/youtube/v3"


# ── YouTube helpers ────────────────────────────────────────────────────────────

def get_channel_videos(channel_id: str, max_videos: int = 5) -> List[Dict]:
    """Return the most recent videos for the given channel."""
    resp = requests.get(
        f"{YT_BASE}/search",
        params={
            "key": YOUTUBE_API_KEY,
            "channelId": channel_id,
            "part": "snippet",
            "order": "date",
            "type": "video",
            "maxResults": max_videos,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {
            "video_id": item["id"]["videoId"],
            "title":    item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
        }
        for item in resp.json().get("items", [])
    ]


def get_video_comments(video_id: str, max_comments: int = 50) -> List[Dict]:
    """Return top-level comments for a video (empty list if comments are disabled)."""
    resp = requests.get(
        f"{YT_BASE}/commentThreads",
        params={
            "key": YOUTUBE_API_KEY,
            "videoId": video_id,
            "part": "snippet",
            "maxResults": min(max_comments, 100),
            "order": "relevance",
            "textFormat": "plainText",
        },
        timeout=15,
    )
    if resp.status_code == 403:
        return []
    resp.raise_for_status()
    return [
        {
            "author":    item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
            "text":      item["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
            "likes":     item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
            "published": item["snippet"]["topLevelComment"]["snippet"]["publishedAt"],
        }
        for item in resp.json().get("items", [])
    ]


# ── Claude analysis ────────────────────────────────────────────────────────────

def analyze_comments_with_claude(videos_with_comments: List[Dict]) -> str:
    """Send all collected comments to Claude and return a structured report."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    comment_blocks = []
    for video in videos_with_comments:
        if not video["comments"]:
            continue
        comment_blocks.append(f"\n### Video: {video['title']}")
        for c in video["comments"]:
            comment_blocks.append(f"- [{c['likes']} likes] {c['text']}")

    if not comment_blocks:
        return "No comments were found across the analyzed videos."

    comments_text = "\n".join(comment_blocks)

    prompt = f"""You are analyzing YouTube comments for a hot sauce brand called "Eruption Hot Sauce".

Below are recent comments across our latest videos:

{comments_text}

Provide a structured analysis with the following sections:

**1. Overall Sentiment**
Estimate the split (e.g. 70% positive / 20% neutral / 10% negative) and describe the general vibe.

**2. What People Love**
Top recurring praise and positive themes. Be specific — quote or paraphrase real comments.

**3. Pain Points & Criticisms**
Honest account of what viewers are unhappy about or requesting. Don't soften these.

**4. Actionable Improvements** (prioritized top 5)
Concrete, specific things the channel owner can do differently based on this feedback.

**5. Content Ideas from the Audience**
Future video topics or formats that commenters seem to want.

**6. Standout Comments** (2–3 worth reading)
Pull the most insightful, funny, or impactful individual comments.

Keep the tone direct and practical — this is a working report, not a feel-good summary."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def _markdown_to_html(text: str) -> str:
    """Minimal markdown → HTML conversion for the email body."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Numbered headers like **1. Title**
    text = re.sub(r"<strong>(\d+\. .+?)</strong>", r"<h3>\1</h3>", text)
    # Bullet points
    lines = []
    in_list = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                lines.append("</ul>")
                in_list = False
            lines.append(f"<p>{stripped}</p>" if stripped else "")
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines)


def build_html_email(analysis: str, videos: List[Dict]) -> str:
    """Build an HTML email from the Claude analysis."""
    video_items = "".join(
        f'<li><a href="https://youtube.com/watch?v={v["video_id"]}" style="color:#cc2200;">'
        f'{v["title"]}</a></li>'
        for v in videos
    )
    html_analysis = _markdown_to_html(analysis)
    date_str = datetime.now().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body  {{ font-family: Arial, sans-serif; color: #222; max-width: 680px; margin: 0 auto; padding: 24px; }}
    h1   {{ color: #cc2200; border-bottom: 2px solid #cc2200; padding-bottom: 8px; }}
    h3   {{ color: #cc2200; margin-top: 24px; }}
    ul   {{ padding-left: 20px; }}
    li   {{ margin-bottom: 6px; }}
    .meta {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
    .footer {{ color: #bbb; font-size: 11px; border-top: 1px solid #eee; margin-top: 32px; padding-top: 12px; }}
  </style>
</head>
<body>
  <h1>🌋 Eruption Hot Sauce — YouTube Comment Summary</h1>
  <p class="meta">Generated on {date_str} &nbsp;|&nbsp; {len(videos)} video(s) analyzed</p>

  <h3>Videos Analyzed</h3>
  <ul>{video_items}</ul>
  <hr>

  {html_analysis}

  <p class="footer">
    This report was auto-generated by your YouTube Comment Summary routine.<br>
    Run <code>python3 youtube_summary.py</code> any time, or schedule it as a cron job.
  </p>
</body>
</html>"""


def send_email(subject: str, html_body: str, plain_body: str) -> None:
    """Send the report via Gmail SMTP (SSL)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def _validate_config() -> None:
    missing = [
        name for name, val in {
            "YOUTUBE_API_KEY":    YOUTUBE_API_KEY,
            "YOUTUBE_CHANNEL_ID": YOUTUBE_CHANNEL_ID,
            "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
            "EMAIL_FROM":         EMAIL_FROM,
            "EMAIL_TO":           EMAIL_TO,
            "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
        }.items()
        if not val
    ]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in the values."
        )


def main() -> None:
    _validate_config()

    print(f"Fetching last {MAX_VIDEOS} videos from channel {YOUTUBE_CHANNEL_ID}...")
    videos = get_channel_videos(YOUTUBE_CHANNEL_ID, MAX_VIDEOS)

    if not videos:
        print("No videos found for this channel. Check your YOUTUBE_CHANNEL_ID.")
        return

    print(f"Found {len(videos)} video(s). Fetching comments...\n")
    videos_with_comments = []
    for video in videos:
        comments = get_video_comments(video["video_id"], MAX_COMMENTS_PER_VIDEO)
        videos_with_comments.append({**video, "comments": comments})
        print(f"  ✓ {video['title']!r} — {len(comments)} comment(s)")

    total = sum(len(v["comments"]) for v in videos_with_comments)
    print(f"\nAnalyzing {total} comment(s) with Claude...")
    analysis = analyze_comments_with_claude(videos_with_comments)

    subject  = f"YouTube Comment Summary — {datetime.now().strftime('%B %d, %Y')}"
    html_body = build_html_email(analysis, videos)

    print("Sending email summary...")
    send_email(subject, html_body, analysis)
    print(f"Done! Report sent to {EMAIL_TO}")


if __name__ == "__main__":
    main()
