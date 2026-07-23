#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent video comments, analyzes sentiment with Claude, and emails a summary.

Required environment variables:
  YOUTUBE_API_KEY       - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID    - Your channel ID (e.g. UCxxxxxx) or handle (e.g. @yourhandle)
  GMAIL_USER            - Gmail address to send from/to
  GMAIL_APP_PASSWORD    - Gmail app password (not your main password)
  ANTHROPIC_API_KEY     - Anthropic API key for Claude sentiment analysis
"""
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
CHANNEL_IDENTIFIER = os.environ["YOUTUBE_CHANNEL_ID"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "75"))


def resolve_channel_id(youtube, identifier):
    """Accept a channel ID (UCxxx), handle (@name), or search term."""
    if identifier.startswith("UC"):
        return identifier
    if identifier.startswith("@"):
        handle = identifier.lstrip("@")
        resp = youtube.channels().list(part="id", forHandle=handle).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"]
    # Fall back to search
    resp = youtube.search().list(
        part="id", q=identifier, type="channel", maxResults=1
    ).execute()
    items = resp.get("items", [])
    if items:
        return items[0]["id"]["channelId"]
    raise ValueError(f"Could not resolve channel for: {identifier}")


def get_recent_videos(youtube, channel_id, max_results=5):
    resp = youtube.search().list(
        part="id,snippet",
        channelId=channel_id,
        maxResults=max_results,
        order="date",
        type="video",
    ).execute()
    return [
        (item["id"]["videoId"], item["snippet"]["title"])
        for item in resp.get("items", [])
    ]


def get_video_comments(youtube, video_id, max_results=75):
    comments = []
    try:
        resp = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance",
            textFormat="plainText",
        ).execute()
        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": top["textDisplay"],
                "likes": top.get("likeCount", 0),
            })
    except HttpError as e:
        if e.resp.status == 403:
            print(f"  Comments disabled for video {video_id}, skipping.")
        else:
            print(f"  Error fetching comments for {video_id}: {e}")
    return comments


def analyze_comments(video_comments_data):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    sections = []
    for title, comments in video_comments_data.items():
        lines = [f"\n### {title}"]
        for c in comments:
            likes = f"[{c['likes']} likes] " if c["likes"] else ""
            lines.append(f"- {likes}{c['text'][:300]}")
        sections.append("\n".join(lines))

    prompt = f"""You are analyzing YouTube comments for a content creator. Based on the comments below, produce a concise weekly digest with these sections:

1. **Overall Sentiment** – How are viewers feeling about the content overall?
2. **What's Landing Well** – Specific things viewers love or praise.
3. **Improvement Areas** – Honest critique or recurring complaints.
4. **Viewer Requests** – Features, topics, or formats viewers are asking for.
5. **Top 3 Action Items** – Prioritized, specific things to act on this week.

Keep it direct and actionable. Skip generic advice.

---
COMMENTS BY VIDEO:
{''.join(sections)}
"""

    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())


def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Resolving channel: {CHANNEL_IDENTIFIER}")
    channel_id = resolve_channel_id(youtube, CHANNEL_IDENTIFIER)
    print(f"Channel ID: {channel_id}")

    print(f"Fetching {MAX_VIDEOS} most recent videos...")
    videos = get_recent_videos(youtube, channel_id, max_results=MAX_VIDEOS)
    if not videos:
        print("No videos found — nothing to send.")
        return

    video_comments_data = {}
    total_comments = 0
    for video_id, title in videos:
        print(f"  Fetching comments: {title[:60]}")
        comments = get_video_comments(youtube, video_id, max_results=MAX_COMMENTS_PER_VIDEO)
        if comments:
            video_comments_data[title] = comments
            total_comments += len(comments)
            print(f"    → {len(comments)} comments")

    if not video_comments_data:
        print("No comments found across any videos.")
        send_email(
            "YouTube Digest: No comments found",
            f"Checked {len(videos)} recent videos but found no comments to analyze.\n\nVideos checked:\n"
            + "\n".join(f"  - {t}" for _, t in videos),
        )
        return

    print(f"\nAnalyzing {total_comments} comments with Claude...")
    analysis = analyze_comments(video_comments_data)

    video_list = "\n".join(
        f"  • {title} ({len(video_comments_data.get(title, []))} comments)"
        for _, title in videos
        if title in video_comments_data
    )

    body = f"""YouTube Comment Digest
======================
Videos analyzed : {len(video_comments_data)}
Comments reviewed: {total_comments}

Videos:
{video_list}

─────────────────────────────────────
{analysis}
─────────────────────────────────────
Generated automatically by youtube_digest.py
"""

    subject = f"YouTube Digest — {len(video_comments_data)} videos, {total_comments} comments"
    print("Sending email...")
    send_email(subject, body)
    print("Done! Digest sent to", GMAIL_USER)


if __name__ == "__main__":
    main()
