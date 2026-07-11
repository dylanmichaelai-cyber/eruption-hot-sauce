#!/usr/bin/env python3
"""
Fetches recent YouTube comments for a channel and outputs structured JSON.
Usage: YOUTUBE_API_KEY=... YOUTUBE_CHANNEL_ID=... python3 fetch_youtube_comments.py
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta, timezone

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
DAYS_BACK = int(os.environ.get("DAYS_BACK", "7"))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "100"))
BASE_URL = "https://www.googleapis.com/youtube/v3"


def api_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
    if not resp.ok:
        error = resp.json().get("error", {})
        raise RuntimeError(f"YouTube API error on /{endpoint}: {error.get('message', resp.text)}")
    return resp.json()


def get_recent_videos(channel_id):
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = api_get("search", {
        "part": "id,snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "publishedAfter": since,
        "maxResults": MAX_VIDEOS,
    })
    videos = [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
            "description": item["snippet"]["description"][:200],
        }
        for item in data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    if not videos:
        data = api_get("search", {
            "part": "id,snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": MAX_VIDEOS,
        })
        videos = [
            {
                "id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "published": item["snippet"]["publishedAt"],
                "description": item["snippet"]["description"][:200],
            }
            for item in data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
    return videos


def get_comments(video_id):
    try:
        data = api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": MAX_COMMENTS_PER_VIDEO,
            "textFormat": "plainText",
        })
    except RuntimeError as e:
        return [], str(e)

    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "author": top.get("authorDisplayName", ""),
            "text": top.get("textDisplay", ""),
            "likes": top.get("likeCount", 0),
            "published": top.get("publishedAt", ""),
        })
    return comments, None


def main():
    errors = []

    if not YOUTUBE_API_KEY:
        errors.append("YOUTUBE_API_KEY environment variable not set")
    if not YOUTUBE_CHANNEL_ID:
        errors.append(
            "YOUTUBE_CHANNEL_ID environment variable not set. "
            "Find your channel ID at youtube.com → Your channel → About → Share → Copy channel ID"
        )

    if errors:
        print(json.dumps({"errors": errors}))
        sys.exit(1)

    try:
        videos = get_recent_videos(YOUTUBE_CHANNEL_ID)
    except RuntimeError as e:
        print(json.dumps({"errors": [str(e)]}))
        sys.exit(1)

    results = []
    for video in videos:
        comments, err = get_comments(video["id"])
        entry = {
            "video_id": video["id"],
            "video_title": video["title"],
            "published": video["published"],
            "url": f"https://www.youtube.com/watch?v={video['id']}",
            "comment_count": len(comments),
            "comments": comments,
        }
        if err:
            entry["error"] = err
        results.append(entry)

    total = sum(v["comment_count"] for v in results)
    print(json.dumps({
        "channel_id": YOUTUBE_CHANNEL_ID,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days_back": DAYS_BACK,
        "videos_found": len(results),
        "total_comments": total,
        "videos": results,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
