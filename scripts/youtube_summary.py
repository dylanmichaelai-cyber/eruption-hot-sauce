#!/usr/bin/env python3
"""
YouTube Comment Summary — fetches recent video comments and generates
AI-powered insights about viewer sentiment and improvement areas.

Usage:
    python3 scripts/youtube_summary.py

Environment variables (set in .env or export):
    YOUTUBE_API_KEY       — YouTube Data API v3 key (required)
    ANTHROPIC_API_KEY     — Anthropic API key for Claude (required)
    YOUTUBE_CHANNEL_ID    — Your channel ID (optional if YOUTUBE_HANDLE set)
    YOUTUBE_HANDLE        — Your @handle without the @ (optional fallback)
    MAX_VIDEOS            — How many recent videos to scan (default: 10)
    MAX_COMMENTS          — Comments per video (default: 75)
"""

import os
import sys
import json
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from dotenv import load_dotenv
import anthropic

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
HANDLE = os.getenv("YOUTUBE_HANDLE", "").strip()
MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "10"))
MAX_COMMENTS = int(os.getenv("MAX_COMMENTS", "75"))

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
SUMMARY_RECIPIENT = os.getenv("SUMMARY_RECIPIENT", "").strip()

YT = "https://www.googleapis.com/youtube/v3"


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def resolve_channel_id():
    """Return channel ID — uses env var, or resolves from @handle."""
    if CHANNEL_ID:
        return CHANNEL_ID
    if HANDLE:
        r = requests.get(f"{YT}/channels", params={
            "key": YOUTUBE_API_KEY,
            "forHandle": HANDLE,
            "part": "id",
        })
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return items[0]["id"]
    raise RuntimeError(
        "Could not determine channel ID. "
        "Set YOUTUBE_CHANNEL_ID or YOUTUBE_HANDLE in .env"
    )


def get_recent_videos(channel_id):
    """Return list of {video_id, title, published} dicts."""
    r = requests.get(f"{YT}/search", params={
        "key": YOUTUBE_API_KEY,
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "type": "video",
        "maxResults": MAX_VIDEOS,
    })
    r.raise_for_status()
    out = []
    for item in r.json().get("items", []):
        out.append({
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        })
    return out


def get_comments(video_id):
    """Return list of comment text strings for a video."""
    r = requests.get(f"{YT}/commentThreads", params={
        "key": YOUTUBE_API_KEY,
        "videoId": video_id,
        "part": "snippet",
        "maxResults": MAX_COMMENTS,
        "order": "relevance",
        "textFormat": "plainText",
    })
    if r.status_code == 403:
        return []  # comments disabled
    r.raise_for_status()
    return [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in r.json().get("items", [])
    ]


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def analyze(video_data):
    """Send comment data to Claude and return a formatted summary string."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    payload = [
        {
            "title": v["title"],
            "published": v["published"],
            "comment_count": len(v["comments"]),
            "comments": v["comments"],
        }
        for v in video_data
        if v["comments"]
    ]

    if not payload:
        return "No comments found on recent videos."

    prompt = f"""You are a YouTube growth advisor reviewing comments for a content creator.
Here is the recent video data (JSON):

{json.dumps(payload, indent=2, ensure_ascii=False)}

Write a clear, actionable summary report with these sections:

## Overall Sentiment
Rate the general viewer mood (Very Positive / Positive / Mixed / Negative) and explain why.

## What Viewers Love
Top 3–5 things viewers consistently praise. Be specific, quote comments where helpful.

## Areas to Improve
Top 3–5 concrete, actionable improvements suggested by or inferred from the comments.

## Recurring Questions / Content Gaps
Questions that appear frequently — these are video ideas you should make.

## Quick Wins
2–3 small changes the creator can make immediately to lift engagement or satisfaction.

Keep the tone honest but encouraging. Use plain English, no fluff."""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not YOUTUBE_API_KEY:
        sys.exit("ERROR: YOUTUBE_API_KEY is not set.")
    if not ANTHROPIC_API_KEY:
        sys.exit("ERROR: ANTHROPIC_API_KEY is not set.")

    print("Resolving channel…")
    channel_id = resolve_channel_id()
    print(f"Channel ID: {channel_id}")

    print(f"Fetching up to {MAX_VIDEOS} recent videos…")
    videos = get_recent_videos(channel_id)
    if not videos:
        sys.exit("No videos found on this channel.")

    print(f"Found {len(videos)} video(s). Fetching comments…")
    for v in videos:
        v["comments"] = get_comments(v["video_id"])
        print(f"  [{v['published']}] {v['title'][:60]}  — {len(v['comments'])} comments")

    total_comments = sum(len(v["comments"]) for v in videos)
    print(f"\nTotal comments collected: {total_comments}")
    print("Analysing with Claude…\n")

    summary = analyze(videos)

    # Build the full email body
    date_str = datetime.now().strftime("%B %d, %Y")
    header = (
        f"YouTube Comment Summary — {date_str}\n"
        f"{'='*55}\n"
        f"Videos scanned: {len(videos)}  |  Comments analysed: {total_comments}\n\n"
    )

    video_list = "\n".join(
        f"  • [{v['published']}] {v['title']} ({len(v['comments'])} comments)"
        for v in videos
    )

    full_report = (
        f"{header}"
        f"Videos covered:\n{video_list}\n\n"
        f"{'='*55}\n\n"
        f"{summary}\n\n"
        f"{'='*55}\n"
        f"Generated by your YouTube Summary routine.\n"
    )

    print(full_report)

    # Save to file so the calling process (or Claude Code hook) can read it
    out_path = Path(__file__).parent / "_last_summary.txt"
    out_path.write_text(full_report, encoding="utf-8")
    print(f"\n[Summary saved to {out_path}]")

    # Send email if credentials are configured
    if GMAIL_ADDRESS and GMAIL_APP_PASSWORD and SUMMARY_RECIPIENT:
        send_email(full_report, date_str)
    else:
        print(
            "[Email skipped — set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, "
            "and SUMMARY_RECIPIENT in .env to enable auto-sending]"
        )

    return full_report


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(report_text, date_str):
    """Send the summary via Gmail SMTP using an app password."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"YouTube Comment Summary — {date_str}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = SUMMARY_RECIPIENT

    # Plain-text part
    msg.attach(MIMEText(report_text, "plain"))

    # HTML part — light formatting for readability
    html_body = (
        "<html><body style='font-family:sans-serif;max-width:700px;margin:auto'>"
        + report_text
        .replace("\n## ", "<h2>").replace("\n", "<br>")
        .replace("<h2>", "</p><h2>").replace("</p>", "", 1)
        + "</body></html>"
    )
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, SUMMARY_RECIPIENT, msg.as_string())
        print(f"[Email sent to {SUMMARY_RECIPIENT}]")
    except Exception as e:
        print(f"[Email failed: {e}]")


if __name__ == "__main__":
    main()
