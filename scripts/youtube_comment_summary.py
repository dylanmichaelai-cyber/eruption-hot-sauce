#!/usr/bin/env python3
"""
YouTube Comment Summary Routine

Fetches recent comments from your YouTube channel, analyzes sentiment and
improvement suggestions using Claude, then emails you a summary.

Setup:
  1. Set env vars (see .env.example in this folder)
  2. Run: python3 youtube_comment_summary.py
  3. Optional cron (weekly): 0 9 * * 1 /path/to/python3 /path/to/youtube_comment_summary.py
"""

import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import anthropic
except ImportError:
    print("Missing dependencies. Run: pip install google-api-python-client anthropic")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config — override any of these with environment variables
# ---------------------------------------------------------------------------

YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY",   "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
CHANNEL_ID        = os.environ.get("YOUTUBE_CHANNEL_ID", "")   # required — see find_channel_id() below
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY",  "")   # your Anthropic key

GMAIL_USER        = os.environ.get("GMAIL_USER",         "d.mcderm80@gmail.com")
GMAIL_APP_PASSWORD= os.environ.get("GMAIL_APP_PASSWORD", "")   # Gmail app password (not your login password)
TO_EMAIL          = os.environ.get("TO_EMAIL",            "d.mcderm80@gmail.com")

MAX_VIDEOS           = int(os.environ.get("MAX_VIDEOS",    "5"))   # recent videos to scan
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS", "50"))  # top-level comments per video
DAYS_BACK            = int(os.environ.get("DAYS_BACK",     "30"))   # only include comments this recent


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def build_youtube():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def find_channel_id(youtube, handle_or_username: str) -> str:
    """
    Resolve a @handle or legacy username to a channel ID.
    Pass the result to YOUTUBE_CHANNEL_ID so you only need to do this once.
    """
    # Try as a @handle (forHandle param)
    try:
        resp = youtube.channels().list(part="id", forHandle=handle_or_username).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"]
    except HttpError:
        pass

    # Fall back to legacy username
    try:
        resp = youtube.channels().list(part="id", forUsername=handle_or_username).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"]
    except HttpError:
        pass

    raise ValueError(f"Could not resolve '{handle_or_username}' to a channel ID.")


def get_recent_videos(youtube, channel_id: str) -> list[dict]:
    """Return up to MAX_VIDEOS recent uploads with id, title, published_at."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * 5)  # broad window; filter comments below

    search_resp = youtube.search().list(
        part="id,snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=MAX_VIDEOS,
        publishedAfter=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
    ).execute()

    videos = []
    for item in search_resp.get("items", []):
        videos.append({
            "id":           item["id"]["videoId"],
            "title":        item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "url":          f"https://www.youtube.com/watch?v={item['id']['videoId']}",
        })
    return videos


def get_video_comments(youtube, video_id: str, cutoff_days: int) -> list[dict]:
    """Return recent top-level comments for a video."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
    comments = []

    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=MAX_COMMENTS_PER_VIDEO,
            order="relevance",
            textFormat="plainText",
        )
        while request and len(comments) < MAX_COMMENTS_PER_VIDEO:
            resp = request.execute()
            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                published = datetime.fromisoformat(top["publishedAt"].replace("Z", "+00:00"))
                if published < cutoff:
                    continue
                comments.append({
                    "text":       top["textDisplay"],
                    "likes":      top["likeCount"],
                    "author":     top["authorDisplayName"],
                    "published":  top["publishedAt"],
                })
            request = youtube.commentThreads().list_next(request, resp)
    except HttpError as e:
        if e.resp.status == 403:
            # Comments disabled on this video
            pass
        else:
            raise

    return comments


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def analyze_with_claude(videos_with_comments: list[dict]) -> str:
    """Send all comments to Claude and get a structured summary."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build a compact payload for Claude
    payload_lines = []
    total_comments = 0
    for v in videos_with_comments:
        payload_lines.append(f'\n### Video: "{v["title"]}" ({v["url"]})')
        if not v["comments"]:
            payload_lines.append("  (no recent comments)")
            continue
        for c in v["comments"]:
            payload_lines.append(f'  - [{c["likes"]} likes] {c["text"]}')
            total_comments += 1

    comments_text = "\n".join(payload_lines)
    today = datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are analyzing YouTube comments for a hot sauce brand called ERUPTION.
Today is {today}. Below are recent comments across {len(videos_with_comments)} videos ({total_comments} total comments).

{comments_text}

Please produce a structured email-ready report with these sections:

1. **Overall Sentiment** — a 2-3 sentence snapshot of how viewers feel overall, with a rough positive/neutral/negative split.

2. **What People Love** — bullet list of the top 3-5 specific things commenters praise (flavors, presentation, energy, storytelling, etc.)

3. **What People Criticize or Question** — bullet list of complaints, confusion, or constructive criticism. Be honest.

4. **Actionable Improvements** — bullet list of 4-6 concrete things you can do to improve future videos based on this feedback. Be specific and practical.

5. **Standout Comments** — 3 notable quotes (positive, critical, and funny/interesting) worth reading.

Keep the tone direct and useful. Format in clean HTML that renders well in Gmail."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str):
    """Send an HTML email via Gmail SMTP using an app password."""
    if not GMAIL_APP_PASSWORD:
        print("\n[Email skipped — GMAIL_APP_PASSWORD not set]")
        print("Summary:\n")
        # Strip tags for terminal fallback
        import re
        plain = re.sub(r"<[^>]+>", "", html_body)
        print(plain)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL

    plain_fallback = "Please view this email in an HTML-capable client."
    msg.attach(MIMEText(plain_fallback, "plain"))
    msg.attach(MIMEText(html_body,      "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())

    print(f"Email sent to {TO_EMAIL}")


def build_html_email(analysis: str, videos: list[dict], total_comments: int) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    video_list_html = "".join(
        f'<li><a href="{v["url"]}">{v["title"]}</a> '
        f'({len(v["comments"])} comments analyzed)</li>'
        for v in videos
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #222; }}
  h1 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 8px; }}
  h2 {{ color: #c0392b; margin-top: 28px; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  ul {{ line-height: 1.7; }}
  blockquote {{ border-left: 4px solid #c0392b; margin: 0; padding: 4px 16px; background: #fdf0f0; }}
  .footer {{ margin-top: 40px; font-size: 12px; color: #999; border-top: 1px solid #ddd; padding-top: 12px; }}
</style>
</head>
<body>
<h1>🌋 ERUPTION — YouTube Comment Summary</h1>
<p class="meta">
  Generated: {today} &nbsp;|&nbsp;
  Videos analyzed: {len(videos)} &nbsp;|&nbsp;
  Comments reviewed: {total_comments}
</p>
<h2>Videos Covered</h2>
<ul>{video_list_html}</ul>
<hr>
{analysis}
<div class="footer">
  This report was generated automatically by the ERUPTION YouTube Comment Routine.<br>
  To unsubscribe or change frequency, edit the cron schedule in scripts/youtube_comment_summary.py.
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate config
    if not YOUTUBE_API_KEY:
        sys.exit("Error: YOUTUBE_API_KEY not set.")
    if not ANTHROPIC_API_KEY:
        sys.exit("Error: ANTHROPIC_API_KEY not set. Get one at console.anthropic.com")

    channel_id = CHANNEL_ID
    youtube = build_youtube()

    if not channel_id:
        print("YOUTUBE_CHANNEL_ID not set.")
        handle = input("Enter your YouTube @handle or username (e.g. @EruptionHotSauce): ").strip()
        channel_id = find_channel_id(youtube, handle)
        print(f"Found channel ID: {channel_id}")
        print(f"Set YOUTUBE_CHANNEL_ID={channel_id} in your environment to skip this step.\n")

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {channel_id}...")
    videos = get_recent_videos(youtube, channel_id)

    if not videos:
        sys.exit("No videos found. Check your YOUTUBE_CHANNEL_ID.")

    print(f"Found {len(videos)} videos. Fetching comments (last {DAYS_BACK} days)...")
    total_comments = 0
    for v in videos:
        v["comments"] = get_video_comments(youtube, v["id"], DAYS_BACK)
        total_comments += len(v["comments"])
        print(f"  {v['title'][:60]!r}: {len(v['comments'])} comments")

    if total_comments == 0:
        sys.exit("No comments found in the selected time window. Try increasing DAYS_BACK.")

    print(f"\nAnalyzing {total_comments} comments with Claude...")
    analysis_html = analyze_with_claude(videos)

    subject = f"ERUPTION YouTube Summary — {datetime.now().strftime('%B %Y')}"
    html_email = build_html_email(analysis_html, videos, total_comments)

    send_email(subject, html_email)
    print("Done.")


if __name__ == "__main__":
    main()
