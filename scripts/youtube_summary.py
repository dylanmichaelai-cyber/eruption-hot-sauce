#!/usr/bin/env python3
"""Fetch YouTube comments from recent videos and print JSON for analysis."""

import sys
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone

API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
DAYS_BACK = int(os.environ.get("YOUTUBE_DAYS_BACK", "7"))
MAX_VIDEOS = 10
MAX_COMMENTS_PER_VIDEO = 100


def youtube_get(endpoint, params):
    params["key"] = API_KEY
    url = "https://www.googleapis.com/youtube/v3/" + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API error {e.code}: {body}")


def fetch_recent_videos(channel_id):
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = youtube_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "maxResults": MAX_VIDEOS,
        "publishedAfter": since,
    })
    return [
        {
            "videoId": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "publishedAt": item["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
    ]


def fetch_comments(video_id):
    try:
        data = youtube_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": MAX_COMMENTS_PER_VIDEO,
            "order": "relevance",
        })
    except RuntimeError as e:
        if "commentsDisabled" in str(e) or "403" in str(e):
            return []
        raise
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text": top.get("textDisplay", ""),
            "likes": top.get("likeCount", 0),
            "author": top.get("authorDisplayName", ""),
            "publishedAt": top.get("publishedAt", ""),
        })
    return comments


def main():
    if not CHANNEL_ID:
        print(json.dumps({
            "error": "YOUTUBE_CHANNEL_ID not set. Set it as an environment variable or update the script.",
            "hint": "Find your channel ID at youtube.com → Your channel → About → Share → Copy channel ID"
        }))
        sys.exit(1)

    try:
        videos = fetch_recent_videos(CHANNEL_ID)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    if not videos:
        print(json.dumps({
            "channelId": CHANNEL_ID,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "daysBack": DAYS_BACK,
            "videos": [],
            "message": f"No videos published in the last {DAYS_BACK} days."
        }))
        sys.exit(0)

    results = []
    for v in videos:
        comments = fetch_comments(v["videoId"])
        results.append({
            "videoId": v["videoId"],
            "title": v["title"],
            "publishedAt": v["publishedAt"],
            "url": f"https://youtu.be/{v['videoId']}",
            "commentCount": len(comments),
            "comments": comments,
        })

    print(json.dumps({
        "channelId": CHANNEL_ID,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "daysBack": DAYS_BACK,
        "videos": results,
    }, indent=2))


if __name__ == "__main__":
    main()
