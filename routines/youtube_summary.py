#!/usr/bin/env python3
"""
Fetches recent YouTube video comments, analyzes audience sentiment with Claude,
and emails a summary with improvement suggestions.

Usage:
  python youtube_summary.py

Schedule as a cron job, e.g. weekly:
  0 9 * * 1 cd /path/to/routines && python youtube_summary.py
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

try:
    import requests
    from dotenv import load_dotenv
    import anthropic
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

YOUTUBE_API_KEY   = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID        = os.getenv("YOUTUBE_CHANNEL_ID")
CHANNEL_HANDLE    = os.getenv("YOUTUBE_CHANNEL_HANDLE")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_FROM        = os.getenv("EMAIL_FROM")
EMAIL_TO          = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

YOUTUBE_BASE          = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS            = 10
MAX_COMMENTS_PER_VIDEO = 50


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def resolve_channel_id() -> str:
    if CHANNEL_ID:
        return CHANNEL_ID

    if not CHANNEL_HANDLE:
        print("Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE in .env")
        sys.exit(1)

    print(f"Resolving channel handle: {CHANNEL_HANDLE}")
    resp = requests.get(
        f"{YOUTUBE_BASE}/search",
        params={
            "part": "snippet",
            "q": CHANNEL_HANDLE,
            "type": "channel",
            "maxResults": 1,
            "key": YOUTUBE_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        print(f"No channel found for handle: {CHANNEL_HANDLE}")
        sys.exit(1)
    return items[0]["snippet"]["channelId"]


def get_channel_info(channel_id: str) -> tuple[str, str]:
    """Returns (channel_title, uploads_playlist_id)."""
    resp = requests.get(
        f"{YOUTUBE_BASE}/channels",
        params={
            "part": "snippet,contentDetails",
            "id": channel_id,
            "key": YOUTUBE_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        print(f"Channel not found: {channel_id}")
        sys.exit(1)
    title    = items[0]["snippet"]["title"]
    playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return title, playlist


def get_recent_videos(uploads_playlist: str) -> list[dict]:
    resp = requests.get(
        f"{YOUTUBE_BASE}/playlistItems",
        params={
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": MAX_VIDEOS,
            "key": YOUTUBE_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {
            "video_id": item["contentDetails"]["videoId"],
            "title":    item["snippet"]["title"],
        }
        for item in resp.json().get("items", [])
    ]


def get_comments(video_id: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{YOUTUBE_BASE}/commentThreads",
            params={
                "part":       "snippet",
                "videoId":    video_id,
                "maxResults": MAX_COMMENTS_PER_VIDEO,
                "order":      "relevance",
                "textFormat": "plainText",
                "key":        YOUTUBE_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        # 403 means comments are disabled for this video
        if exc.response is not None and exc.response.status_code == 403:
            return []
        raise

    return [
        {
            "author": item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
            "text":   item["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
            "likes":  item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
        }
        for item in resp.json().get("items", [])
    ]


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def analyze_comments(channel_title: str, video_data: list[dict]) -> str:
    total = sum(len(v["comments"]) for v in video_data)
    if total == 0:
        return "No comments were available to analyze."

    lines = [f"YouTube Channel: {channel_title}\n"]
    for v in video_data:
        if not v["comments"]:
            continue
        lines.append(f"\n## {v['title']}")
        for c in v["comments"]:
            text = c["text"][:300].replace("\n", " ")
            lines.append(f"  [{c['likes']} likes] {c['author']}: {text}")

    context = "\n".join(lines)

    prompt = f"""You are analyzing YouTube comments for a content creator. Based on the comments below, write a clear report with these sections:

1. **Overall Sentiment** — One sentence verdict, then approximate positive/neutral/negative split.
2. **What Viewers Love** — Top 3–5 specific things people praise (cite examples).
3. **What Needs Improvement** — Top 3–5 actionable critiques or repeated requests (cite examples).
4. **Recurring Themes** — Patterns or topics mentioned across multiple videos.
5. **Standout Comments** — 2–3 quotes worth reading (one glowing, one constructive).
6. **Action Items** — Exactly 3 concrete next steps the creator should take.

Be direct and specific. Ground every point in actual comments, not generalities.

---
{context}
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def validate_env() -> None:
    required = {
        "YOUTUBE_API_KEY":   YOUTUBE_API_KEY,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM":        EMAIL_FROM,
        "EMAIL_TO":          EMAIL_TO,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
        print("Copy routines/.env.example to routines/.env and fill in the values.")
        sys.exit(1)

    if not CHANNEL_ID and not CHANNEL_HANDLE:
        print("Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE in routines/.env")
        sys.exit(1)


def main() -> None:
    validate_env()

    channel_id              = resolve_channel_id()
    channel_title, playlist = get_channel_info(channel_id)
    print(f"Channel: {channel_title}")

    videos = get_recent_videos(playlist)
    print(f"Found {len(videos)} recent video(s). Fetching comments...")

    video_data = []
    for v in videos:
        comments = get_comments(v["video_id"])
        video_data.append({**v, "comments": comments})
        label = "disabled" if not comments else f"{len(comments)} comments"
        print(f"  {v['title'][:65]!r} — {label}")

    total = sum(len(v["comments"]) for v in video_data)
    print(f"\nAnalyzing {total} comments with Claude...")
    summary = analyze_comments(channel_title, video_data)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject  = f"YouTube Audience Digest — {channel_title} ({date_str})"
    body = f"""YouTube Comment Summary
Generated : {date_str}
Channel   : {channel_title}
Videos    : {len(videos)} | Comments: {total}

{"=" * 60}

{summary}

{"=" * 60}
Sent by youtube_summary.py — schedule with cron to run automatically.
"""

    print(f"Sending summary to {EMAIL_TO}...")
    send_email(subject, body)
    print("Done.")


if __name__ == "__main__":
    main()
