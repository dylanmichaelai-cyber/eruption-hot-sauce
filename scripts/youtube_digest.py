#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel, analyzes sentiment and
improvement suggestions using Claude, then emails you a summary.

Usage:
    python3 youtube_digest.py

Required env vars (set in scripts/.env):
    YOUTUBE_API_KEY       — YouTube Data API v3 key
    YOUTUBE_CHANNEL_ID    — Your channel ID (e.g. UCxxxxxxxxxxxxxxxx)
    ANTHROPIC_API_KEY     — Claude API key
    EMAIL_FROM            — Gmail address to send from
    EMAIL_TO              — Address to deliver the digest to
    EMAIL_APP_PASSWORD    — Gmail App Password (not your login password)

Optional:
    MAX_VIDEOS            — How many recent videos to scan (default: 10)
    MAX_COMMENTS_PER_VIDEO— Max comments per video (default: 50)
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import anthropic

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))


def validate_config():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM": EMAIL_FROM,
        "EMAIL_TO": EMAIL_TO,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: Missing required config in scripts/.env:\n  " + "\n  ".join(missing))
        sys.exit(1)


def fetch_recent_videos(youtube, channel_id, max_results):
    channel_resp = youtube.channels().list(
        part="contentDetails,snippet",
        id=channel_id,
    ).execute()

    if not channel_resp.get("items"):
        print(f"ERROR: Channel '{channel_id}' not found. Check YOUTUBE_CHANNEL_ID in .env.")
        sys.exit(1)

    channel_name = channel_resp["items"][0]["snippet"]["title"]
    uploads_id = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    playlist_resp = youtube.playlistItems().list(
        part="snippet",
        playlistId=uploads_id,
        maxResults=max_results,
    ).execute()

    videos = []
    for item in playlist_resp.get("items", []):
        snippet = item["snippet"]
        videos.append({
            "id": snippet["resourceId"]["videoId"],
            "title": snippet["title"],
            "published_at": snippet["publishedAt"][:10],
        })

    return channel_name, videos


def fetch_comments(youtube, video_id, max_results):
    try:
        resp = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance",
            textFormat="plainText",
        ).execute()
        comments = []
        for item in resp.get("items", []):
            c = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": c["textDisplay"],
                "likes": c["likeCount"],
                "author": c["authorDisplayName"],
            })
        return comments
    except HttpError as e:
        if e.resp.status == 403:
            return []  # comments disabled on this video
        raise


def build_analysis_prompt(video_data):
    sections = []
    for v in video_data:
        if not v["comments"]:
            continue
        lines = "\n".join(
            f"  [{c['likes']} likes] {c['text']}" for c in v["comments"]
        )
        sections.append(f"### {v['title']} (published {v['published_at']})\n{lines}")
    return "\n\n".join(sections)


def analyze_with_claude(client, channel_name, video_data):
    comments_block = build_analysis_prompt(video_data)
    if not comments_block:
        return "No comments were available to analyze."

    total = sum(len(v["comments"]) for v in video_data)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=(
            "You are a helpful YouTube analytics assistant. "
            "Give honest, specific, actionable feedback based on real viewer comments."
        ),
        messages=[{
            "role": "user",
            "content": f"""Analyze the YouTube comments below for the channel "{channel_name}" ({total} comments across {len(video_data)} videos) and write a digest with these sections:

**1. Overall Viewer Sentiment**
One paragraph summarising the general mood and reception.

**2. What Viewers Love**
Bullet list of recurring positive themes (be specific, not generic).

**3. Criticism & Concerns**
Bullet list of complaints or constructive criticism mentioned by viewers.

**4. Actionable Improvements**
5 concrete, prioritised things the creator should do differently in upcoming videos, based directly on the comments.

**5. Standout Comments**
Quote 3 comments verbatim that are especially insightful or representative.

---
{comments_block}
---

Keep each section tight. Focus on patterns, not one-offs. Be honest.""",
        }],
    )
    return response.content[0].text


def send_email(subject, body, from_addr, to_addr, app_password):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, to_addr, msg.as_string())


def main():
    validate_config()

    print("Connecting to YouTube Data API...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching {MAX_VIDEOS} most recent videos from channel {CHANNEL_ID}...")
    channel_name, videos = fetch_recent_videos(youtube, CHANNEL_ID, MAX_VIDEOS)
    print(f"Channel: {channel_name}  ({len(videos)} videos found)")

    print("Fetching comments...")
    video_data = []
    for v in videos:
        comments = fetch_comments(youtube, v["id"], MAX_COMMENTS_PER_VIDEO)
        label = "(comments disabled)" if not comments else f"{len(comments)} comments"
        print(f"  {v['title'][:65]}: {label}")
        video_data.append({**v, "comments": comments})

    total_comments = sum(len(v["comments"]) for v in video_data)
    print(f"\nAnalyzing {total_comments} comments with Claude...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    analysis = analyze_with_claude(client, channel_name, video_data)

    today = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Comment Digest – {channel_name} – {today}"

    video_list = "\n".join(
        f"  • [{v['published_at']}] {v['title'][:65]} ({len(v['comments'])} comments)"
        for v in video_data
    )

    body = f"""YOUTUBE COMMENT DIGEST
Channel : {channel_name}
Date    : {today}
Videos  : {len(video_data)}
Comments: {total_comments}

VIDEOS COVERED
{video_list}

{'=' * 60}
ANALYSIS
{'=' * 60}

{analysis}

{'=' * 60}
Generated by youtube_digest.py
"""

    print(f"Sending digest to {EMAIL_TO}...")
    send_email(subject, body, EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD)
    print("Done — email sent successfully.")


if __name__ == "__main__":
    main()
