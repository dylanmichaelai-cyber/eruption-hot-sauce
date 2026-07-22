#!/usr/bin/env python3
"""
Fetches recent YouTube comments from a channel and prints structured output
for sentiment analysis. Reads config from .env in the project root.
"""

import os
import sys
import json
import requests
from pathlib import Path

# --- Config ---
ROOT = Path(__file__).parent.parent
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "").lstrip("@")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
MAX_VIDEOS = int(os.environ.get("YT_MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("YT_MAX_COMMENTS_PER_VIDEO", "50"))

BASE = "https://www.googleapis.com/youtube/v3"


def yt(endpoint, **params):
    params["key"] = API_KEY
    r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=15)
    data = r.json()
    if "error" in data:
        err = data["error"]
        print(f"ERROR [{err.get('code')}]: {err.get('message')}", file=sys.stderr)
        sys.exit(1)
    return data


def resolve_channel_id():
    if CHANNEL_ID:
        return CHANNEL_ID
    if CHANNEL_HANDLE:
        data = yt("channels", part="id", forHandle=CHANNEL_HANDLE)
        items = data.get("items", [])
        if not items:
            print(f"ERROR: No channel found for handle '@{CHANNEL_HANDLE}'", file=sys.stderr)
            sys.exit(1)
        return items[0]["id"]
    print(
        "ERROR: Set YOUTUBE_CHANNEL_HANDLE or YOUTUBE_CHANNEL_ID in .env\n"
        "  Example: YOUTUBE_CHANNEL_HANDLE=@YourChannelName",
        file=sys.stderr,
    )
    sys.exit(1)


def get_recent_videos(channel_id):
    data = yt(
        "search",
        part="id,snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=MAX_VIDEOS,
    )
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id, video_title):
    try:
        data = yt(
            "commentThreads",
            part="snippet",
            videoId=video_id,
            maxResults=MAX_COMMENTS_PER_VIDEO,
            order="relevance",
        )
    except SystemExit:
        return []

    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text": top["textDisplay"],
            "likes": top["likeCount"],
            "author": top["authorDisplayName"],
        })
    return comments


def main():
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    channel_id = resolve_channel_id()

    # Fetch channel info
    ch_data = yt("channels", part="snippet,statistics", id=channel_id)
    ch_items = ch_data.get("items", [])
    if not ch_items:
        print(f"ERROR: Channel {channel_id} not found", file=sys.stderr)
        sys.exit(1)
    ch = ch_items[0]
    channel_name = ch["snippet"]["title"]
    stats = ch.get("statistics", {})

    print(f"CHANNEL: {channel_name}")
    print(f"SUBSCRIBERS: {stats.get('subscriberCount', 'hidden')}")
    print(f"TOTAL_VIEWS: {stats.get('viewCount', 'N/A')}")
    print(f"TOTAL_VIDEOS: {stats.get('videoCount', 'N/A')}")
    print()

    videos = get_recent_videos(channel_id)
    if not videos:
        print("No recent videos found.", file=sys.stderr)
        sys.exit(1)

    all_comments = []
    for video in videos:
        comments = get_comments(video["id"], video["title"])
        all_comments.append({
            "video_id": video["id"],
            "video_title": video["title"],
            "published": video["published"],
            "url": f"https://youtube.com/watch?v={video['id']}",
            "comment_count": len(comments),
            "comments": comments,
        })

    print(json.dumps(all_comments, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
