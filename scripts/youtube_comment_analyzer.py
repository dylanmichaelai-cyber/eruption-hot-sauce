#!/usr/bin/env python3
"""
YouTube Comment Fetcher
Fetches recent videos and comments from a YouTube channel.
Outputs JSON to stdout for downstream analysis.

Required env var: YOUTUBE_API_KEY
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS = 10
MAX_COMMENTS_PER_VIDEO = 50


def youtube_get(endpoint, params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    resp = requests.get(f"{YOUTUBE_API_BASE}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_channel_info():
    data = youtube_get("channels", {
        "part": "id,snippet,contentDetails",
        "mine": "true",
    })
    items = data.get("items", [])
    if not items:
        raise RuntimeError("No channel found for this API key. Make sure the key has YouTube Data API v3 enabled.")
    ch = items[0]
    return {
        "id": ch["id"],
        "name": ch["snippet"]["title"],
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def get_recent_videos(uploads_playlist_id, max_results=MAX_VIDEOS):
    data = youtube_get("playlistItems", {
        "part": "snippet",
        "playlistId": uploads_playlist_id,
        "maxResults": max_results,
    })
    videos = []
    for item in data.get("items", []):
        sn = item["snippet"]
        videos.append({
            "id": sn["resourceId"]["videoId"],
            "title": sn["title"],
            "published": sn["publishedAt"],
        })
    return videos


def get_comments(video_id, max_results=MAX_COMMENTS_PER_VIDEO):
    try:
        data = youtube_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "relevance",
            "textFormat": "plainText",
        })
    except requests.HTTPError as e:
        if e.response.status_code in (403, 404):
            # Comments disabled or video not found
            return []
        raise
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
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("ERROR: YOUTUBE_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print("Fetching channel info...", file=sys.stderr)
    channel = get_channel_info()
    print(f"Channel: {channel['name']} ({channel['id']})", file=sys.stderr)

    print(f"Fetching up to {MAX_VIDEOS} recent videos...", file=sys.stderr)
    videos = get_recent_videos(channel["uploads_playlist"])
    print(f"Found {len(videos)} videos.", file=sys.stderr)

    video_data = []
    for v in videos:
        print(f"  Fetching comments for: {v['title'][:60]}", file=sys.stderr)
        comments = get_comments(v["id"])
        video_data.append({**v, "comments": comments})

    total_comments = sum(len(v["comments"]) for v in video_data)
    print(f"Total comments collected: {total_comments}", file=sys.stderr)

    output = {
        "channel_name": channel["name"],
        "channel_id": channel["id"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "videos_count": len(videos),
        "total_comments": total_comments,
        "videos": video_data,
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
