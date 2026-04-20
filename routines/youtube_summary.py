#!/usr/bin/env python3
"""
YouTube Comment Summary Routine

Fetches comments from your YouTube channel, analyzes them with Claude,
and emails you a sentiment summary with improvement suggestions.

Setup:
  1. Copy .env.example to .env and fill in values
  2. pip install -r requirements.txt
  3. python youtube_summary.py

Schedule (cron example — weekly on Monday at 9am):
  0 9 * * 1 cd /path/to/routines && python youtube_summary.py
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

YOUTUBE_API_KEY  = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID       = os.getenv("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_FROM       = os.getenv("EMAIL_FROM")
EMAIL_TO         = os.getenv("EMAIL_TO")
EMAIL_PASSWORD   = os.getenv("EMAIL_APP_PASSWORD")  # Gmail App Password
DAYS_LOOKBACK    = int(os.getenv("DAYS_LOOKBACK", "30"))
MAX_VIDEOS       = int(os.getenv("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "100"))


def validate_config():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM": EMAIL_FROM,
        "EMAIL_TO": EMAIL_TO,
        "EMAIL_APP_PASSWORD": EMAIL_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        print("Copy routines/.env.example to routines/.env and fill in all values.")
        sys.exit(1)


def get_recent_videos(youtube):
    """Return list of recent video dicts from the channel."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    videos = []
    next_page = None

    while len(videos) < MAX_VIDEOS:
        params = dict(
            part="snippet",
            channelId=CHANNEL_ID,
            order="date",
            type="video",
            publishedAfter=cutoff,
            maxResults=min(MAX_VIDEOS - len(videos), 50),
        )
        if next_page:
            params["pageToken"] = next_page

        resp = youtube.search().list(**params).execute()
        for item in resp.get("items", []):
            videos.append(
                {
                    "id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "published": item["snippet"]["publishedAt"],
                }
            )

        next_page = resp.get("nextPageToken")
        if not next_page or len(videos) >= MAX_VIDEOS:
            break

    return videos


def get_video_comments(youtube, video_id):
    """Return flat list of top-level comment strings for a video."""
    comments = []
    next_page = None

    while len(comments) < MAX_COMMENTS_PER_VIDEO:
        try:
            params = dict(
                part="snippet",
                videoId=video_id,
                order="relevance",
                maxResults=min(MAX_COMMENTS_PER_VIDEO - len(comments), 100),
                textFormat="plainText",
            )
            if next_page:
                params["pageToken"] = next_page

            resp = youtube.commentThreads().list(**params).execute()
            for item in resp.get("items", []):
                text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                likes = item["snippet"]["topLevelComment"]["snippet"]["likeCount"]
                comments.append({"text": text, "likes": likes})

            next_page = resp.get("nextPageToken")
            if not next_page:
                break
        except HttpError as e:
            if e.resp.status == 403:
                # Comments disabled on this video
                break
            raise

    return comments


def build_claude_prompt(videos_with_comments):
    lines = []
    for v in videos_with_comments:
        lines.append(f"\n=== VIDEO: {v['title']} ===")
        if not v["comments"]:
            lines.append("(no comments available)")
            continue
        for c in v["comments"][:50]:  # cap per video to keep prompt reasonable
            prefix = f"[👍{c['likes']}] " if c["likes"] > 0 else ""
            lines.append(f"- {prefix}{c['text']}")

    comment_block = "\n".join(lines)

    return f"""You are an expert YouTube channel analyst. Below are recent comments from a YouTube creator's videos (last {DAYS_LOOKBACK} days).

{comment_block}

Please provide a concise, actionable email report covering:

1. **Overall Sentiment** – What is the general tone? Positive, mixed, negative? Give a brief summary.

2. **What Viewers Love** – Top 3–5 things viewers consistently praise or respond well to.

3. **Common Criticisms & Pain Points** – Top 3–5 recurring complaints or frustrations.

4. **Improvement Suggestions** – Specific, actionable things the creator can do to improve their content based on viewer feedback. Be direct and concrete.

5. **Standout Comments** – 2–3 particularly insightful or representative comments (quote them).

6. **Quick Stats** – Approximate: total comments analyzed, % positive sentiment, % negative, % neutral.

Format as clean HTML suitable for an email body (use <h2>, <ul>, <li>, <blockquote>, <p> tags). Keep the tone encouraging and constructive.
"""


def analyze_with_claude(videos_with_comments):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = build_claude_prompt(videos_with_comments)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def wrap_email(analysis_html, video_count, comment_count):
    date_str = datetime.now().strftime("%B %d, %Y")
    return f"""
<html><body style="font-family:sans-serif;max-width:680px;margin:auto;color:#222;line-height:1.6">
  <h1 style="color:#FF4500">YouTube Comment Summary</h1>
  <p style="color:#666">{date_str} &nbsp;·&nbsp; {video_count} videos &nbsp;·&nbsp; {comment_count} comments analyzed</p>
  <hr style="border:1px solid #eee">
  {analysis_html}
  <hr style="border:1px solid #eee">
  <p style="color:#aaa;font-size:12px">Generated by your YouTube Comment Summary routine.</p>
</body></html>
"""


def main():
    validate_config()

    print(f"Building YouTube client...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching videos from last {DAYS_LOOKBACK} days...")
    videos = get_recent_videos(youtube)
    if not videos:
        print("No videos found in the lookback window. Exiting.")
        sys.exit(0)

    print(f"Found {len(videos)} video(s). Fetching comments...")
    videos_with_comments = []
    total_comments = 0
    for v in videos:
        comments = get_video_comments(youtube, v["id"])
        total_comments += len(comments)
        videos_with_comments.append({**v, "comments": comments})
        print(f"  {v['title'][:60]}: {len(comments)} comments")

    if total_comments == 0:
        print("No comments found. Exiting.")
        sys.exit(0)

    print(f"\nAnalyzing {total_comments} comments with Claude...")
    analysis_html = analyze_with_claude(videos_with_comments)

    subject = f"YouTube Comment Summary — {datetime.now().strftime('%b %d, %Y')} ({total_comments} comments)"
    email_html = wrap_email(analysis_html, len(videos), total_comments)

    print(f"Sending email to {EMAIL_TO}...")
    send_email(subject, email_html)
    print("Done! Summary email sent.")


if __name__ == "__main__":
    main()
