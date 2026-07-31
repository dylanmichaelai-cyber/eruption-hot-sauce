#!/usr/bin/env python3
"""
Fetches recent YouTube comments for a channel and outputs a structured summary.

Required env vars:
  YOUTUBE_API_KEY          - YouTube Data API v3 key
  YOUTUBE_CHANNEL_HANDLE   - Channel handle e.g. @DylanAutomates (default: @DylanAutomates)
  YOUTUBE_VIDEO_COUNT      - Number of recent videos to scan (default: 5)
  YOUTUBE_COMMENT_COUNT    - Max comments per video (default: 50)
"""

import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

API_BASE = "https://www.googleapis.com/youtube/v3"

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "@DylanAutomates")
VIDEO_COUNT = int(os.environ.get("YOUTUBE_VIDEO_COUNT", "5"))
COMMENT_COUNT = int(os.environ.get("YOUTUBE_COMMENT_COUNT", "50"))


def api_get(endpoint, params):
    params["key"] = API_KEY
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] YouTube API {endpoint}: HTTP {e.code} - {body}", file=sys.stderr)
        sys.exit(1)


def resolve_channel_id(handle):
    # Strip leading @ for forUsername lookup fallback
    username = handle.lstrip("@")
    data = api_get("channels", {
        "part": "id,snippet",
        "forHandle": handle,
        "maxResults": 1,
    })
    items = data.get("items", [])
    if items:
        return items[0]["id"], items[0]["snippet"]["title"]
    # Fallback: search by name
    data = api_get("search", {
        "part": "snippet",
        "q": username,
        "type": "channel",
        "maxResults": 1,
    })
    items = data.get("items", [])
    if items:
        return items[0]["snippet"]["channelId"], items[0]["snippet"]["channelTitle"]
    print(f"[ERROR] Could not find channel for handle: {handle}", file=sys.stderr)
    sys.exit(1)


def get_recent_videos(channel_id, count):
    data = api_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "type": "video",
        "maxResults": count,
    })
    videos = []
    for item in data.get("items", []):
        videos.append({
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        })
    return videos


def get_comments(video_id, max_results):
    try:
        data = api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "relevance",
            "textFormat": "plainText",
        })
    except SystemExit:
        # Comments may be disabled — skip gracefully
        return []
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "author": top["authorDisplayName"],
            "text": top["textDisplay"],
            "likes": top["likeCount"],
            "published": top["publishedAt"][:10],
        })
    return comments


def main():
    if not API_KEY:
        print("[ERROR] YOUTUBE_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    channel_id, channel_title = resolve_channel_id(CHANNEL_HANDLE)

    videos = get_recent_videos(channel_id, VIDEO_COUNT)

    results = {
        "channel": channel_title,
        "channel_id": channel_id,
        "videos": [],
    }

    for video in videos:
        comments = get_comments(video["id"], COMMENT_COUNT)
        results["videos"].append({
            "title": video["title"],
            "video_id": video["id"],
            "published": video["published"],
            "url": f"https://youtu.be/{video['id']}",
            "comment_count": len(comments),
            "comments": comments,
        })

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
