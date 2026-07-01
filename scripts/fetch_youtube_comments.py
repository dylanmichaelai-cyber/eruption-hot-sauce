#!/usr/bin/env python3
"""Fetches recent YouTube comments for a channel and outputs JSON to stdout."""

import json
import sys
import os
import requests
from datetime import datetime, timedelta, timezone

# --- Config (override via environment variables) ---
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "YOUR_API_KEY_HERE")
CHANNEL_ID      = os.environ.get("YOUTUBE_CHANNEL_ID", "YOUR_CHANNEL_ID_HERE")
DAYS_BACK       = int(os.environ.get("YOUTUBE_DAYS_BACK", "7"))
MAX_COMMENTS    = int(os.environ.get("YOUTUBE_MAX_COMMENTS", "100"))


def get_recent_videos(channel_id, api_key, days_back):
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "key": api_key,
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "type": "video",
        "publishedAfter": since,
        "maxResults": 50,
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get("items", [])
    return [(item["id"]["videoId"], item["snippet"]["title"]) for item in items]


def get_comments(video_id, api_key, max_results):
    params = {
        "key": api_key,
        "videoId": video_id,
        "part": "snippet",
        "maxResults": max_results,
        "order": "relevance",
        "textFormat": "plainText",
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/commentThreads", params=params, timeout=15)
    if r.status_code == 403:
        return []  # Comments disabled on this video
    r.raise_for_status()
    comments = []
    for item in r.json().get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text": top["textDisplay"],
            "likes": top["likeCount"],
            "published": top["publishedAt"],
        })
    return comments


def main():
    if YOUTUBE_API_KEY == "YOUR_API_KEY_HERE":
        print(json.dumps({"error": "YOUTUBE_API_KEY not configured"}))
        sys.exit(1)
    if CHANNEL_ID == "YOUR_CHANNEL_ID_HERE":
        print(json.dumps({"error": "YOUTUBE_CHANNEL_ID not configured"}))
        sys.exit(1)

    videos = get_recent_videos(CHANNEL_ID, YOUTUBE_API_KEY, DAYS_BACK)

    if not videos:
        print(json.dumps({"videos": [], "message": f"No videos found in the last {DAYS_BACK} days."}))
        return

    results = []
    for video_id, title in videos:
        comments = get_comments(video_id, YOUTUBE_API_KEY, MAX_COMMENTS)
        results.append({
            "video_id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "comment_count": len(comments),
            "comments": comments,
        })

    print(json.dumps({"videos": results}, indent=2))


if __name__ == "__main__":
    main()
