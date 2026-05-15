#!/usr/bin/env python3
"""
Fetches recent comments from all videos on a YouTube channel
and saves them to comments.json for analysis.

Usage:
  python3 scripts/fetch_youtube_comments.py

Required env vars:
  YOUTUBE_API_KEY      - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID   - Your channel ID (e.g. UCxxxxxxxxxxxxxxxx)
                         Find it at: youtube.com > Your channel > About > Share > Copy channel ID

Optional env vars:
  YOUTUBE_MAX_VIDEOS   - How many recent videos to scan (default: 10)
  YOUTUBE_MAX_COMMENTS - Max comments per video (default: 100)
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
MAX_VIDEOS = int(os.environ.get("YOUTUBE_MAX_VIDEOS", "10"))
MAX_COMMENTS = int(os.environ.get("YOUTUBE_MAX_COMMENTS", "100"))

BASE = "https://www.googleapis.com/youtube/v3"


def get(endpoint, **params):
    params["key"] = API_KEY
    resp = requests.get(f"{BASE}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_recent_videos(channel_id):
    data = get(
        "search",
        channelId=channel_id,
        part="id,snippet",
        order="date",
        type="video",
        maxResults=MAX_VIDEOS,
    )
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
    ]


def fetch_comments(video_id, max_results):
    comments = []
    page_token = None

    while len(comments) < max_results:
        params = dict(
            part="snippet",
            videoId=video_id,
            maxResults=min(100, max_results - len(comments)),
            textFormat="plainText",
            order="relevance",
        )
        if page_token:
            params["pageToken"] = page_token

        try:
            data = get("commentThreads", **params)
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                # Comments disabled on this video
                break
            raise

        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append(
                {
                    "text": top["textDisplay"],
                    "likes": top["likeCount"],
                    "published": top["publishedAt"],
                }
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return comments


def main():
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    if not CHANNEL_ID:
        print("ERROR: YOUTUBE_CHANNEL_ID not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {CHANNEL_ID}...")
    videos = fetch_recent_videos(CHANNEL_ID)
    print(f"Found {len(videos)} videos.")

    results = []
    for video in videos:
        print(f"  Fetching comments for: {video['title'][:60]}")
        comments = fetch_comments(video["id"], MAX_COMMENTS)
        results.append(
            {
                "video_id": video["id"],
                "title": video["title"],
                "published": video["published"],
                "url": f"https://youtube.com/watch?v={video['id']}",
                "comment_count": len(comments),
                "comments": comments,
            }
        )
        print(f"    -> {len(comments)} comments collected.")

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": CHANNEL_ID,
        "total_comments": sum(v["comment_count"] for v in results),
        "videos": results,
    }

    out_path = os.path.join(os.path.dirname(__file__), "comments.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {output['total_comments']} comments to {out_path}")


if __name__ == "__main__":
    main()
