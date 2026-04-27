#!/usr/bin/env python3
"""
YouTube Comment Summary Routine

Fetches recent YouTube comments, analyzes sentiment and feedback with Claude,
then emails a summary report to you.

Usage:
    python youtube_summary.py

Schedule with cron (daily at 9am):
    0 9 * * * cd /path/to/project && python routines/youtube_summary.py
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")


def get_recent_videos(youtube, channel_id, max_results=10):
    channels_resp = youtube.channels().list(
        id=channel_id,
        part="contentDetails"
    ).execute()

    if not channels_resp.get("items"):
        raise ValueError(f"Channel not found: {channel_id}")

    uploads_id = (
        channels_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    playlist_resp = youtube.playlistItems().list(
        playlistId=uploads_id,
        part="snippet",
        maxResults=max_results,
    ).execute()

    return [
        {
            "id": item["snippet"]["resourceId"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
        }
        for item in playlist_resp.get("items", [])
    ]


def get_video_comments(youtube, video_id, max_results=100):
    comments = []
    try:
        resp = youtube.commentThreads().list(
            videoId=video_id,
            part="snippet",
            maxResults=max_results,
            order="relevance",
        ).execute()
        for item in resp.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": snippet["textDisplay"],
                "likes": snippet["likeCount"],
                "author": snippet["authorDisplayName"],
            })
    except Exception as e:
        print(f"  Warning: could not fetch comments for {video_id}: {e}")
    return comments


def analyze_with_claude(videos_with_comments):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = ["Here are YouTube comments from your recent videos:\n"]
    for video in videos_with_comments:
        lines.append(f"\n### Video: {video['title']}")
        if video["comments"]:
            for c in video["comments"][:50]:
                lines.append(f"- {c['text']}")
        else:
            lines.append("(No comments available)")

    lines.append("""

Please analyze these YouTube comments and write a detailed email-ready report:

1. **Overall Sentiment** — Approximate positive/neutral/negative split and dominant mood.

2. **What Viewers Love** — Specific things people appreciate most.

3. **Constructive Criticism & Improvement Areas** — Actionable feedback and patterns of frustration.

4. **Recurring Questions & Topics** — Common themes viewers keep bringing up.

5. **Top 5 Action Items** — Concrete, prioritized steps to improve the channel.

Keep the tone encouraging but honest. Format it cleanly.""")

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": "\n".join(lines)}],
    ) as stream:
        final = stream.get_final_message()

    text_blocks = [b for b in final.content if b.type == "text"]
    return text_blocks[-1].text if text_blocks else "No analysis generated."


def send_email(subject, body, to_addr, from_addr, app_password):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, to_addr, msg.as_string())


def main():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": YOUTUBE_CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM": EMAIL_FROM,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy routines/.env.example to routines/.env and fill in the values."
        )

    dest = EMAIL_TO or EMAIL_FROM

    print("Connecting to YouTube API...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching recent videos for channel: {YOUTUBE_CHANNEL_ID}")
    videos = get_recent_videos(youtube, YOUTUBE_CHANNEL_ID)
    print(f"Found {len(videos)} videos.")

    videos_with_comments = []
    for video in videos:
        print(f"  Fetching comments: {video['title']}")
        comments = get_video_comments(youtube, video["id"])
        videos_with_comments.append({**video, "comments": comments})
        print(f"    {len(comments)} comment(s) fetched.")

    print("Analyzing comments with Claude...")
    analysis = analyze_with_claude(videos_with_comments)

    today = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Comment Analysis — {today}"
    body = f"""YouTube Comment Analysis Report
Generated: {today}
Videos Analyzed: {len(videos_with_comments)}
{"=" * 60}

{analysis}

{"=" * 60}
This report was generated automatically by your YouTube Comment Summary routine.
"""

    print(f"Sending report to {dest}...")
    send_email(subject, body, dest, EMAIL_FROM, EMAIL_APP_PASSWORD)
    print("Done! Check your inbox.")


if __name__ == "__main__":
    main()
