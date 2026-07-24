#!/usr/bin/env python3
"""
Fetches recent YouTube video comments for a channel and prints JSON to stdout.
Usage: python3 youtube_comment_analyzer.py
Reads config from youtube_config.json in the same directory.
"""
import json
import sys
import urllib.request
import urllib.parse
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "youtube_config.json")

BASE_URL = "https://www.googleapis.com/youtube/v3"


def api_get(endpoint, params):
    url = f"{BASE_URL}/{endpoint}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} from YouTube API: {body}")


def fetch_recent_videos(api_key, channel_id, max_results):
    data = api_get("search", {
        "part": "id,snippet",
        "channelId": channel_id,
        "maxResults": max_results,
        "order": "date",
        "type": "video",
        "key": api_key,
    })
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "description": item["snippet"]["description"][:200],
        }
        for item in data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]


def fetch_comments(api_key, video_id, max_results):
    try:
        data = api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max_results,
            "order": "relevance",
            "key": api_key,
        })
        comments = []
        for item in data.get("items", []):
            c = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author": c["authorDisplayName"],
                "text": c["textDisplay"],
                "likes": c["likeCount"],
                "published_at": c["publishedAt"],
            })
        return comments
    except RuntimeError as e:
        return [{"error": str(e)}]


def main():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    api_key = config["api_key"]
    channel_id = config["channel_id"]
    max_videos = config.get("max_videos", 5)
    max_comments = config.get("max_comments_per_video", 50)

    if channel_id == "YOUR_YOUTUBE_CHANNEL_ID":
        print(json.dumps({"error": "channel_id not configured in youtube_config.json"}))
        sys.exit(1)

    videos = fetch_recent_videos(api_key, channel_id, max_videos)
    results = []
    for video in videos:
        comments = fetch_comments(api_key, video["video_id"], max_comments)
        results.append({**video, "comments": comments})

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
