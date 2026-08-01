#!/usr/bin/env python3
"""
Fetch recent comments from a YouTube channel and output structured JSON.
Requires: pip install requests
Usage: YOUTUBE_API_KEY=... YOUTUBE_CHANNEL_ID=... python3 youtube_comment_summary.py
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
BASE_URL = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS = 10
MAX_COMMENTS_PER_VIDEO = 50


def api_get(endpoint, params):
    params["key"] = API_KEY
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_recent_videos(channel_id):
    data = api_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "type": "video",
        "maxResults": MAX_VIDEOS,
    })
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id):
    try:
        data = api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": MAX_COMMENTS_PER_VIDEO,
        })
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return []  # comments disabled
        raise
    return [
        {
            "author": item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
            "text": item["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
            "likes": item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
            "published": item["snippet"]["topLevelComment"]["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
    ]


def main():
    if not API_KEY:
        print(json.dumps({"error": "YOUTUBE_API_KEY environment variable not set"}))
        sys.exit(1)
    if not CHANNEL_ID:
        print(json.dumps({"error": "YOUTUBE_CHANNEL_ID environment variable not set"}))
        sys.exit(1)

    videos = get_recent_videos(CHANNEL_ID)
    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": CHANNEL_ID,
        "videos": [],
    }

    for video in videos:
        comments = get_comments(video["id"])
        result["videos"].append({
            "id": video["id"],
            "title": video["title"],
            "published": video["published"],
            "comment_count": len(comments),
            "comments": comments,
        })

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
