#!/usr/bin/env python3
"""
YouTube Comment Analyzer
Fetches recent video comments from a YouTube channel and outputs a structured
summary for sentiment analysis and improvement insights.

Required environment variables:
  YOUTUBE_API_KEY      - YouTube Data API v3 key (from Google Cloud Console)
  YOUTUBE_CHANNEL_ID   - YouTube channel ID (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)

Optional:
  DAYS_BACK            - How many days of videos to analyze (default: 7)
  MAX_VIDEOS           - Max number of recent videos to analyze (default: 10)
  MAX_COMMENTS_PER_VIDEO - Max comments per video (default: 100)
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta


YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
DAYS_BACK = int(os.environ.get("DAYS_BACK", "7"))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "100"))

BASE_URL = "https://www.googleapis.com/youtube/v3"


def api_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_recent_videos(channel_id, days_back, max_results):
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = api_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "publishedAfter": published_after,
        "maxResults": max_results,
    })
    return data.get("items", [])


def get_video_comments(video_id, max_results):
    try:
        data = api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "relevance",
        })
    except requests.HTTPError as e:
        if e.response.status_code in (403, 404):
            return []  # Comments disabled or video not found
        raise

    comments = []
    for thread in data.get("items", []):
        snip = thread["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text": snip["textDisplay"],
            "likes": snip.get("likeCount", 0),
            "author": snip.get("authorDisplayName", "Anonymous"),
            "published_at": snip.get("publishedAt", ""),
        })
    return comments


def main():
    errors = []
    if not YOUTUBE_API_KEY:
        errors.append("YOUTUBE_API_KEY environment variable is not set.")
    if not CHANNEL_ID:
        errors.append("YOUTUBE_CHANNEL_ID environment variable is not set.")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching videos from the last {DAYS_BACK} days...", file=sys.stderr)
    videos = get_recent_videos(CHANNEL_ID, DAYS_BACK, MAX_VIDEOS)

    if not videos:
        print("No recent videos found in the specified time window.", file=sys.stderr)
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "channel_id": CHANNEL_ID,
            "days_analyzed": DAYS_BACK,
            "video_count": 0,
            "total_comments": 0,
            "videos": [],
        }
        print(json.dumps(result, indent=2))
        return

    all_videos_data = []
    for video in videos:
        video_id = video["id"]["videoId"]
        title = video["snippet"]["title"]
        published = video["snippet"].get("publishedAt", "")
        print(f"Fetching comments for: {title}", file=sys.stderr)
        comments = get_video_comments(video_id, MAX_COMMENTS_PER_VIDEO)
        all_videos_data.append({
            "title": title,
            "video_id": video_id,
            "published_at": published,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "comment_count": len(comments),
            "comments": comments,
        })

    total_comments = sum(v["comment_count"] for v in all_videos_data)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": CHANNEL_ID,
        "days_analyzed": DAYS_BACK,
        "video_count": len(all_videos_data),
        "total_comments": total_comments,
        "videos": all_videos_data,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
