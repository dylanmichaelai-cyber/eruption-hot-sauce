#!/usr/bin/env python3
"""
YouTube Comment Analyzer
Fetches comments from your YouTube channel, analyzes sentiment and improvement
suggestions using Claude, then emails you a summary.

Setup:
  1. pip install -r requirements.txt
  2. Fill in .env (copy from .env.example)
  3. python youtube_analyzer.py

To schedule weekly (every Monday at 8am), add to crontab:
  0 8 * * 1 cd /path/to/eruption-hot-sauce && python youtube_analyzer.py
"""

import os
import sys
import smtplib
import textwrap
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from googleapiclient.discovery import build
import anthropic

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")
MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "100"))


def check_config():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_SENDER": EMAIL_SENDER,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
        "EMAIL_RECIPIENT": EMAIL_RECIPIENT,
    }
    missing = [k for k, v in required.items() if not v or v.startswith("your_")]
    if missing:
        print("ERROR: Missing or unconfigured values in .env:")
        for key in missing:
            print(f"  - {key}")
        sys.exit(1)


def get_channel_videos(youtube):
    """Return up to MAX_VIDEOS recent uploads from the channel."""
    # Get the uploads playlist ID
    channel_resp = youtube.channels().list(
        part="contentDetails,snippet",
        id=CHANNEL_ID,
    ).execute()

    if not channel_resp.get("items"):
        print(f"ERROR: Channel '{CHANNEL_ID}' not found. Check YOUTUBE_CHANNEL_ID in .env.")
        sys.exit(1)

    channel_name = channel_resp["items"][0]["snippet"]["title"]
    uploads_playlist = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Walk the uploads playlist
    videos = []
    next_page_token = None

    while len(videos) < MAX_VIDEOS:
        playlist_resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist,
            maxResults=min(50, MAX_VIDEOS - len(videos)),
            pageToken=next_page_token,
        ).execute()

        for item in playlist_resp.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "published_at": snippet["publishedAt"],
            })

        next_page_token = playlist_resp.get("nextPageToken")
        if not next_page_token:
            break

    return channel_name, videos


def get_video_comments(youtube, video_id):
    """Return top-level comments for a video, up to MAX_COMMENTS_PER_VIDEO."""
    comments = []
    next_page_token = None

    try:
        while len(comments) < MAX_COMMENTS_PER_VIDEO:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, MAX_COMMENTS_PER_VIDEO - len(comments)),
                order="relevance",
                pageToken=next_page_token,
            ).execute()

            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "author": top["authorDisplayName"],
                    "text": top["textDisplay"],
                    "likes": top["likeCount"],
                    "reply_count": item["snippet"]["totalReplyCount"],
                })

            next_page_token = resp.get("nextPageToken")
            if not next_page_token:
                break

    except Exception as e:
        # Comments may be disabled on the video
        if "commentsDisabled" in str(e) or "403" in str(e):
            return []
        raise

    return comments


def build_comment_digest(channel_name, videos_with_comments):
    """Assemble a compact text digest of all comments to send to Claude."""
    lines = [f"YouTube Channel: {channel_name}", ""]

    for video in videos_with_comments:
        lines.append(f"VIDEO: {video['title']} (published {video['published_at'][:10]})")
        comments = video["comments"]
        if not comments:
            lines.append("  (no comments or comments disabled)")
        else:
            lines.append(f"  {len(comments)} comments fetched:")
            for c in comments:
                likes_tag = f" [{c['likes']} likes]" if c["likes"] > 0 else ""
                lines.append(f"  - {c['text'].strip()}{likes_tag}")
        lines.append("")

    return "\n".join(lines)


def analyze_with_claude(digest):
    """Ask Claude to produce a structured sentiment + improvement report."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = textwrap.dedent("""
        You are an expert YouTube audience analyst. You analyze viewer comments and
        produce clear, actionable reports for content creators. Be specific, honest,
        and constructive. Focus on patterns, not isolated comments.
    """).strip()

    user_prompt = textwrap.dedent(f"""
        Analyze the YouTube comments below and write a concise report with these sections:

        ## Overall Sentiment
        A 2-3 sentence summary of how viewers feel overall (positive / mixed / negative)
        and the dominant emotional tone.

        ## What Viewers Love
        Bullet list of the top things viewers consistently praise or enjoy.

        ## What Viewers Dislike or Find Confusing
        Bullet list of recurring criticisms, confusion points, or complaints.

        ## Suggested Improvements
        Actionable bullet list of content improvements based directly on the feedback.
        Be specific — reference actual comment patterns.

        ## Standout Comments
        Quote 3-5 of the most insightful or representative comments (positive or
        constructive), with brief notes on why each is worth the creator's attention.

        ---
        {digest}
    """).strip()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    return message.content[0].text


def build_email_html(channel_name, report, videos_analyzed, total_comments):
    """Wrap the Claude report in a clean HTML email."""
    # Convert markdown-ish headers to HTML
    html_report = report
    for level, tag in [("## ", "h2"), ("### ", "h3")]:
        lines = html_report.split("\n")
        new_lines = []
        for line in lines:
            if line.startswith(level):
                text = line[len(level):]
                new_lines.append(f"<{tag}>{text}</{tag}>")
            else:
                new_lines.append(line)
        html_report = "\n".join(new_lines)

    # Convert bullet lines
    lines = html_report.split("\n")
    new_lines = []
    in_list = False
    for line in lines:
        if line.startswith("- "):
            if not in_list:
                new_lines.append("<ul>")
                in_list = True
            new_lines.append(f"<li>{line[2:]}</li>")
        else:
            if in_list:
                new_lines.append("</ul>")
                in_list = False
            new_lines.append(f"<p>{line}</p>" if line.strip() else "")
    if in_list:
        new_lines.append("</ul>")
    html_report = "\n".join(new_lines)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 680px; margin: 0 auto; padding: 24px; color: #1a1a1a; }}
  h1   {{ color: #ff4500; border-bottom: 2px solid #ff4500; padding-bottom: 8px; }}
  h2   {{ color: #cc3700; margin-top: 28px; }}
  h3   {{ color: #333; }}
  .meta {{ background: #f5f5f5; padding: 12px 16px; border-radius: 6px;
           font-size: 14px; color: #555; margin-bottom: 24px; }}
  ul   {{ padding-left: 20px; line-height: 1.7; }}
  li   {{ margin-bottom: 6px; }}
  p    {{ line-height: 1.6; }}
  blockquote {{ border-left: 4px solid #ff4500; margin: 0; padding-left: 16px;
                color: #555; font-style: italic; }}
  .footer {{ margin-top: 40px; font-size: 12px; color: #aaa; border-top: 1px solid #eee;
             padding-top: 16px; }}
</style>
</head>
<body>
<h1>YouTube Audience Report</h1>
<div class="meta">
  <strong>Channel:</strong> {channel_name} &nbsp;|&nbsp;
  <strong>Date:</strong> {date_str} &nbsp;|&nbsp;
  <strong>Videos analyzed:</strong> {videos_analyzed} &nbsp;|&nbsp;
  <strong>Total comments:</strong> {total_comments}
</div>
{html_report}
<div class="footer">Generated by youtube_analyzer.py &mdash; powered by Claude</div>
</body>
</html>"""


def send_email(subject, html_body, plain_body):
    """Send an HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())


def main():
    print("YouTube Comment Analyzer")
    print("=" * 40)

    check_config()

    print("Connecting to YouTube API...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {CHANNEL_ID}...")
    channel_name, videos = get_channel_videos(youtube)
    print(f"Found channel: {channel_name} ({len(videos)} videos)")

    videos_with_comments = []
    total_comments = 0

    for i, video in enumerate(videos, 1):
        print(f"  [{i}/{len(videos)}] Fetching comments: {video['title'][:60]}...")
        comments = get_video_comments(youtube, video["id"])
        video["comments"] = comments
        videos_with_comments.append(video)
        total_comments += len(comments)
        print(f"         → {len(comments)} comments")

    print(f"\nTotal comments collected: {total_comments}")

    if total_comments == 0:
        print("No comments found — nothing to analyze. Exiting.")
        sys.exit(0)

    print("\nAnalyzing comments with Claude...")
    digest = build_comment_digest(channel_name, videos_with_comments)
    report = analyze_with_claude(digest)

    print("Building email...")
    subject = f"YouTube Audience Report — {channel_name} — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
    html_body = build_email_html(channel_name, report, len(videos_with_comments), total_comments)

    print(f"Sending email to {EMAIL_RECIPIENT}...")
    send_email(subject, html_body, report)

    print("\nDone! Email sent successfully.")
    print("\n--- Report Preview ---")
    print(report[:500] + "..." if len(report) > 500 else report)


if __name__ == "__main__":
    main()
