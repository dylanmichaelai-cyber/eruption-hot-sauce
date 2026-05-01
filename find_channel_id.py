#!/usr/bin/env python3
"""
Helper to find your YouTube channel ID.

Usage:
    python find_channel_id.py "@YourHandle"
    python find_channel_id.py "Your Channel Name"
"""

import sys
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]


def find_channel(query: str) -> None:
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    # Try handle lookup first (e.g. @eruption)
    if query.startswith("@"):
        response = (
            youtube.channels()
            .list(part="id,snippet", forHandle=query.lstrip("@"))
            .execute()
        )
    else:
        response = (
            youtube.search()
            .list(part="id,snippet", type="channel", q=query, maxResults=5)
            .execute()
        )

    items = response.get("items", [])
    if not items:
        print("No channels found for that query.")
        return

    print("\nMatching channels:")
    for item in items:
        channel_id = item.get("id") if isinstance(item.get("id"), str) else item["id"].get("channelId")
        title = item["snippet"]["title"]
        description = item["snippet"].get("description", "")[:80]
        print(f"\n  Title      : {title}")
        print(f"  Channel ID : {channel_id}")
        print(f"  Description: {description}")

    print("\nCopy the Channel ID into your .env file as YOUTUBE_CHANNEL_ID=...")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python find_channel_id.py \"@YourHandle\" or \"Channel Name\"")
        sys.exit(1)
    find_channel(sys.argv[1])
