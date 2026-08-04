#!/usr/bin/env python3
"""
Fetch recent YouTube video comments for a channel.
Outputs structured JSON to stdout for downstream analysis.

Usage:
    python3 youtube_comments.py [channel_id]

Config via environment variables:
    YOUTUBE_API_KEY   - YouTube Data API v3 key
    YOUTUBE_CHANNEL_ID - Channel ID (overridden by positional arg)
"""
import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
CHANNEL_ID = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("YOUTUBE_CHANNEL_ID", "")
MAX_VIDEOS = 10
MAX_COMMENTS_PER_VIDEO = 50


def yt_fetch(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"YouTube API error {e.code}: {body}")


def get_channel_id_from_handle(handle):
    """Look up a channel ID from a @handle or username."""
    data = yt_fetch("channels", {"part": "id", "forHandle": handle})
    items = data.get("items", [])
    if items:
        return items[0]["id"]
    # Fallback: search
    data = yt_fetch("search", {"part": "snippet", "q": handle, "type": "channel", "maxResults": 1})
    items = data.get("items", [])
    if items:
        return items[0]["id"]["channelId"]
    return None


def get_recent_videos(channel_id):
    data = yt_fetch("search", {
        "part": "snippet",
        "channelId": channel_id,
        "maxResults": MAX_VIDEOS,
        "order": "date",
        "type": "video",
    })
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "url": f"https://youtube.com/watch?v={item['id']['videoId']}",
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id):
    try:
        data = yt_fetch("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": MAX_COMMENTS_PER_VIDEO,
            "order": "relevance",
        })
    except RuntimeError:
        return []

    comments = []
    for item in data.get("items", []):
        c = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text": c["textDisplay"],
            "likes": c["likeCount"],
            "author": c["authorDisplayName"],
            "published_at": c["publishedAt"],
        })
    return comments


def main():
    if not YOUTUBE_API_KEY:
        print(json.dumps({"error": "YOUTUBE_API_KEY not set"}))
        sys.exit(1)

    channel_id = CHANNEL_ID
    if not channel_id:
        print(json.dumps({"error": "YOUTUBE_CHANNEL_ID not set and no channel_id argument provided"}))
        sys.exit(1)

    # Allow @handle as input
    if channel_id.startswith("@"):
        channel_id = get_channel_id_from_handle(channel_id)
        if not channel_id:
            print(json.dumps({"error": f"Could not resolve handle {CHANNEL_ID}"}))
            sys.exit(1)

    videos = get_recent_videos(channel_id)
    results = []
    for video in videos:
        comments = get_comments(video["video_id"])
        results.append({**video, "comment_count": len(comments), "comments": comments})

    output = {
        "channel_id": channel_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "video_count": len(results),
        "videos": results,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
