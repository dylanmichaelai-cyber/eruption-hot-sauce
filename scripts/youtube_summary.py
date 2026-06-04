#!/usr/bin/env python3
"""
YouTube Comments Summary
Fetches recent video comments and prints a structured report for Claude to analyze.
Required env vars: YOUTUBE_API_KEY, YOUTUBE_CHANNEL_ID (or YOUTUBE_CHANNEL_HANDLE)
"""

import json
import os
import sys
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
BASE_URL = "https://www.googleapis.com/youtube/v3"


def api_get(endpoint, params):
    params["key"] = API_KEY
    url = f"{BASE_URL}/{endpoint}?{urlencode(params)}"
    try:
        with urlopen(url) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode()
        print(f"YouTube API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def get_channel_id():
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID", "")
    if channel_id:
        return channel_id

    handle = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "")
    if handle:
        handle = handle.lstrip("@")
        data = api_get("channels", {"part": "id,snippet", "forHandle": handle})
        items = data.get("items", [])
        if items:
            return items[0]["id"]
        print(f"No channel found for handle @{handle}", file=sys.stderr)
        sys.exit(1)

    print(
        "Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE environment variable.",
        file=sys.stderr,
    )
    sys.exit(1)


def get_recent_videos(channel_id, count=5):
    data = api_get(
        "search",
        {
            "part": "id,snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": count,
        },
    )
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id, max_results=100):
    data = api_get(
        "commentThreads",
        {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "relevance",
        },
    )
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append(
            {
                "text": top["textOriginal"],
                "likes": top["likeCount"],
                "author": top["authorDisplayName"],
            }
        )
    return comments


def main():
    if not API_KEY:
        print("YOUTUBE_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    channel_id = get_channel_id()

    # Get channel info
    channel_data = api_get("channels", {"part": "snippet", "id": channel_id})
    channel_name = "Unknown"
    if channel_data.get("items"):
        channel_name = channel_data["items"][0]["snippet"]["title"]

    videos = get_recent_videos(channel_id, count=5)
    if not videos:
        print("No videos found for this channel.", file=sys.stderr)
        sys.exit(1)

    report = {"channel": channel_name, "videos": []}

    for video in videos:
        comments = get_comments(video["id"])
        report["videos"].append(
            {
                "title": video["title"],
                "published": video["published"],
                "url": f"https://youtube.com/watch?v={video['id']}",
                "comment_count": len(comments),
                "comments": comments,
            }
        )

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
