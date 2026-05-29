#!/usr/bin/env python3
"""
YouTube Comment Analysis Routine
Fetches recent comments from your YouTube channel, analyzes them with Claude,
and emails you a summary of viewer sentiment and improvement suggestions.

Setup: copy .env.example to .env and fill in your credentials.
Run:   python3 youtube_summary.py
Cron:  0 9 * * 1 /usr/bin/python3 /path/to/youtube_summary.py  (every Monday 9am)
"""

import os
import sys
import smtplib
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
import anthropic

# ── Configuration ──────────────────────────────────────────────────────────────

def load_env(path=".env"):
    """Load key=value pairs from a .env file into os.environ."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

load_env()

YOUTUBE_API_KEY    = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO           = os.environ.get("EMAIL_TO", GMAIL_USER)
MAX_VIDEOS         = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"

# ── YouTube helpers ────────────────────────────────────────────────────────────

def yt_get(endpoint, **params):
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YOUTUBE_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_recent_videos(channel_id, max_results=10):
    data = yt_get(
        "search",
        channelId=channel_id,
        part="snippet",
        order="date",
        type="video",
        maxResults=max_results,
    )
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id, max_results=50):
    try:
        data = yt_get(
            "commentThreads",
            videoId=video_id,
            part="snippet",
            order="relevance",
            maxResults=min(max_results, 100),
        )
    except requests.HTTPError as e:
        # Comments may be disabled on some videos
        if e.response.status_code in (403, 400):
            return []
        raise

    return [
        {
            "text": item["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
            "likes": item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
        }
        for item in data.get("items", [])
    ]

# ── Analysis ───────────────────────────────────────────────────────────────────

def build_prompt(videos_with_comments):
    sections = []
    for v in videos_with_comments:
        if not v["comments"]:
            continue
        lines = "\n".join(f"  • {c['text']}" for c in v["comments"])
        sections.append(f"### {v['title']} ({v['published']})\n{lines}")

    if not sections:
        return None

    body = "\n\n".join(sections)
    return f"""You are analyzing YouTube comments for a content creator.
Below are recent comments grouped by video. Provide a structured report with these sections:

1. **Overall Sentiment** — one paragraph on how viewers feel in general.
2. **What viewers love** — bullet list of recurring praise or excitement.
3. **Constructive criticism** — bullet list of complaints, confusion, or requests.
4. **Improvement recommendations** — 4-6 specific, actionable things the creator can do differently.
5. **Standout comments** — 2-3 high-impact comments worth reading in full (quote them).

Be concise, honest, and practical. Skip fluff.

---

{body}"""


def analyze_with_claude(prompt):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text

# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(subject, plain_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(plain_body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())

# ── Main ───────────────────────────────────────────────────────────────────────

def check_config():
    missing = [
        name for name, val in [
            ("YOUTUBE_API_KEY",    YOUTUBE_API_KEY),
            ("YOUTUBE_CHANNEL_ID", YOUTUBE_CHANNEL_ID),
            ("ANTHROPIC_API_KEY",  ANTHROPIC_API_KEY),
            ("GMAIL_USER",         GMAIL_USER),
            ("GMAIL_APP_PASSWORD", GMAIL_APP_PASSWORD),
        ]
        if not val
    ]
    if missing:
        print("Missing configuration values:", ", ".join(missing))
        print("Copy .env.example → .env and fill them in.")
        sys.exit(1)


def main():
    check_config()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] Fetching videos for channel {YOUTUBE_CHANNEL_ID}...")

    videos = get_recent_videos(YOUTUBE_CHANNEL_ID, MAX_VIDEOS)
    if not videos:
        print("No videos found. Check YOUTUBE_CHANNEL_ID.")
        sys.exit(1)

    print(f"Found {len(videos)} video(s). Fetching comments...")
    for v in videos:
        v["comments"] = get_comments(v["id"], MAX_COMMENTS_PER_VIDEO)
        total = len(v["comments"])
        print(f"  {v['title'][:60]!r} — {total} comment(s)")

    total_comments = sum(len(v["comments"]) for v in videos)
    if total_comments == 0:
        print("No comments found across any video.")
        sys.exit(0)

    print(f"\nAnalyzing {total_comments} comment(s) with Claude...")
    prompt = build_prompt(videos)
    if not prompt:
        print("Nothing to analyze.")
        sys.exit(0)

    analysis = analyze_with_claude(prompt)

    subject = f"YouTube Insights — {datetime.now().strftime('%B %d, %Y')}"
    email_body = (
        f"YouTube Comment Analysis\n"
        f"Generated: {now}\n"
        f"Videos: {len(videos)}  |  Comments analyzed: {total_comments}\n"
        f"{'─' * 60}\n\n"
        f"{analysis}\n\n"
        f"{'─' * 60}\n"
        f"Run youtube_summary.py again anytime to refresh this report.\n"
    )

    print(f"\nSending summary to {EMAIL_TO}...")
    send_email(subject, email_body)
    print("Done. Email sent.")


if __name__ == "__main__":
    main()
