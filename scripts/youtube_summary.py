#!/usr/bin/env python3
"""
Fetch YouTube comments from a channel's recent videos and print a structured summary.
Used by the Claude Code weekly routine to generate comment digest emails.

Usage:
    YOUTUBE_API_KEY=<key> YOUTUBE_CHANNEL_ID=<id> python3 scripts/youtube_summary.py

Env vars:
    YOUTUBE_API_KEY     - YouTube Data API v3 key
    YOUTUBE_CHANNEL_ID  - Your channel ID (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)
                          Find it at: youtube.com/account_advanced
    LOOKBACK_DAYS       - How many days back to scan (default: 7)
    MAX_VIDEOS          - Max videos to scan (default: 10)
    MAX_COMMENTS        - Max comments per video (default: 100)
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

API_BASE = "https://www.googleapis.com/youtube/v3"


def yt_get(endpoint, params):
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        err = body.get("error", {})
        print(f"YouTube API error {e.code}: {err.get('message', 'unknown')}", file=sys.stderr)
        sys.exit(1)


def get_uploads_playlist(api_key, channel_id):
    data = yt_get("channels", {
        "part": "contentDetails",
        "id": channel_id,
        "key": api_key,
    })
    items = data.get("items", [])
    if not items:
        print(f"Channel '{channel_id}' not found.", file=sys.stderr)
        sys.exit(1)
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_recent_videos(api_key, playlist_id, max_videos, lookback_days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    videos = []
    page_token = None
    while len(videos) < max_videos:
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": min(50, max_videos - len(videos)),
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        data = yt_get("playlistItems", params)
        for item in data.get("items", []):
            snip = item["snippet"]
            published = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            if published < cutoff:
                return videos
            videos.append({
                "id": snip["resourceId"]["videoId"],
                "title": snip["title"],
                "published": snip["publishedAt"],
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return videos


def get_comments(api_key, video_id, max_comments):
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": min(100, max_comments),
        "order": "relevance",
        "key": api_key,
        "textFormat": "plainText",
    }
    data = yt_get("commentThreads", params)
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "author": top["authorDisplayName"],
            "text": top["textDisplay"],
            "likes": top["likeCount"],
            "published": top["publishedAt"],
        })
    return comments


def main():
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
    lookback_days = int(os.environ.get("LOOKBACK_DAYS", "7"))
    max_videos = int(os.environ.get("MAX_VIDEOS", "10"))
    max_comments = int(os.environ.get("MAX_COMMENTS", "100"))

    if not api_key:
        print("ERROR: YOUTUBE_API_KEY env var is required.", file=sys.stderr)
        sys.exit(1)
    if not channel_id:
        print("ERROR: YOUTUBE_CHANNEL_ID env var is required.", file=sys.stderr)
        print("Find your channel ID at: youtube.com > Account > Advanced settings", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching videos from last {lookback_days} days (max {max_videos} videos)...", file=sys.stderr)
    playlist_id = get_uploads_playlist(api_key, channel_id)
    videos = get_recent_videos(api_key, playlist_id, max_videos, lookback_days)

    if not videos:
        print(json.dumps({"videos": [], "total_comments": 0, "comments_by_video": []}))
        return

    print(f"Found {len(videos)} video(s). Fetching comments...", file=sys.stderr)

    results = []
    total = 0
    for v in videos:
        comments = get_comments(api_key, v["id"], max_comments)
        total += len(comments)
        results.append({
            "video_id": v["id"],
            "title": v["title"],
            "published": v["published"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "comment_count": len(comments),
            "comments": comments,
        })
        print(f"  {v['title']}: {len(comments)} comments", file=sys.stderr)

    output = {
        "channel_id": channel_id,
        "period_days": lookback_days,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_comments": total,
        "videos": results,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
