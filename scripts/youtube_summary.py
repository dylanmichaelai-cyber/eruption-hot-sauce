#!/usr/bin/env python3
"""
Fetches recent YouTube video comments for a channel and outputs structured JSON.
Used by the weekly comment analysis cron routine.

Usage:
  python3 youtube_summary.py --channel-id UC... --api-key AIza... [--max-videos 10] [--max-comments 100]
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import urllib.error


def fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body)
        except Exception:
            msg = body
        print(f"HTTP {e.code} from YouTube API: {msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)


def get_recent_videos(channel_id, api_key, max_results):
    params = urllib.parse.urlencode({
        "part": "snippet",
        "channelId": channel_id,
        "maxResults": max_results,
        "order": "date",
        "type": "video",
        "key": api_key,
    })
    data = fetch_json(f"https://www.googleapis.com/youtube/v3/search?{params}")
    videos = []
    for item in data.get("items", []):
        videos.append({
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
            "description": item["snippet"]["description"][:200],
        })
    return videos


def get_comments(video_id, api_key, max_results):
    params = urllib.parse.urlencode({
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max_results,
        "order": "relevance",
        "key": api_key,
    })
    data = fetch_json(f"https://www.googleapis.com/youtube/v3/commentThreads?{params}")
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text": top["textDisplay"],
            "likes": top.get("likeCount", 0),
            "author": top["authorDisplayName"],
            "published": top["publishedAt"],
        })
    return comments


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube comments for analysis")
    parser.add_argument("--channel-id", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--max-videos", type=int, default=10)
    parser.add_argument("--max-comments", type=int, default=100)
    args = parser.parse_args()

    print(f"Fetching {args.max_videos} recent videos...", file=sys.stderr)
    videos = get_recent_videos(args.channel_id, args.api_key, args.max_videos)

    if not videos:
        print(json.dumps({"error": "No videos found. Check channel ID and API key."}))
        sys.exit(1)

    results = []
    for video in videos:
        print(f"  Fetching comments: {video['title'][:60]}", file=sys.stderr)
        comments = get_comments(video["id"], args.api_key, args.max_comments)
        results.append({
            "video_id": video["id"],
            "title": video["title"],
            "published": video["published"],
            "url": f"https://www.youtube.com/watch?v={video['id']}",
            "comment_count": len(comments),
            "comments": comments,
        })

    print(json.dumps({
        "channel_id": args.channel_id,
        "total_videos_analyzed": len(results),
        "total_comments": sum(r["comment_count"] for r in results),
        "videos": results,
    }, indent=2))


if __name__ == "__main__":
    main()
