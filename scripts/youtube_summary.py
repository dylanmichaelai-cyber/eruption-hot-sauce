#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches recent comments from a YouTube channel and prints a structured JSON
summary suitable for AI analysis.

Required env vars:
  YOUTUBE_API_KEY        - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID     - Channel ID (e.g. UCxxxxxxxxxxxxxx)
                           OR set YOUTUBE_CHANNEL_HANDLE (e.g. @mychannel)

Optional env vars:
  VIDEOS_TO_SCAN         - Number of recent videos to fetch (default: 5)
  COMMENTS_PER_VIDEO     - Max comments to fetch per video (default: 100)
"""

import os
import sys
import json
import requests

API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "").strip()
VIDEOS_TO_SCAN = int(os.environ.get("VIDEOS_TO_SCAN", "5"))
COMMENTS_PER_VIDEO = int(os.environ.get("COMMENTS_PER_VIDEO", "100"))

BASE = "https://www.googleapis.com/youtube/v3"


def yt_get(endpoint, **params):
    params["key"] = API_KEY
    resp = requests.get(f"{BASE}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def resolve_channel_id():
    if CHANNEL_ID:
        return CHANNEL_ID
    if CHANNEL_HANDLE:
        handle = CHANNEL_HANDLE.lstrip("@")
        data = yt_get("channels", part="id", forHandle=handle)
        items = data.get("items", [])
        if items:
            return items[0]["id"]
        raise ValueError(f"No channel found for handle: @{handle}")
    raise ValueError(
        "Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE environment variable."
    )


def get_uploads_playlist(channel_id):
    data = yt_get("channels", part="contentDetails,snippet", id=channel_id)
    items = data.get("items", [])
    if not items:
        raise ValueError(f"Channel not found: {channel_id}")
    ch = items[0]
    return (
        ch["snippet"]["title"],
        ch["contentDetails"]["relatedPlaylists"]["uploads"],
    )


def get_recent_videos(playlist_id):
    data = yt_get(
        "playlistItems",
        part="snippet",
        playlistId=playlist_id,
        maxResults=VIDEOS_TO_SCAN,
    )
    videos = []
    for item in data.get("items", []):
        s = item["snippet"]
        videos.append(
            {
                "id": s["resourceId"]["videoId"],
                "title": s["title"],
                "published": s["publishedAt"],
                "url": f"https://www.youtube.com/watch?v={s['resourceId']['videoId']}",
            }
        )
    return videos


def get_comments(video_id):
    try:
        data = yt_get(
            "commentThreads",
            part="snippet",
            videoId=video_id,
            maxResults=COMMENTS_PER_VIDEO,
            order="relevance",
            textFormat="plainText",
        )
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            # Comments disabled for this video
            return []
        raise
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
        print("ERROR: YOUTUBE_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    channel_id = resolve_channel_id()
    channel_name, playlist_id = get_uploads_playlist(channel_id)
    videos = get_recent_videos(playlist_id)

    results = []
    for video in videos:
        comments = get_comments(video["id"])
        results.append(
            {
                "video": video,
                "total_comments_fetched": len(comments),
                "comments": comments,
            }
        )

    output = {
        "channel": channel_name,
        "channel_id": channel_id,
        "videos_scanned": len(results),
        "data": results,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
