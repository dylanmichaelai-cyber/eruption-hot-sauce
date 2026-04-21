#!/usr/bin/env python3
"""
Fetches recent YouTube comments, analyzes sentiment with Claude,
and emails a summary report to the channel owner.
"""

import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# Config — all values come from environment variables (see .env.example)
# ---------------------------------------------------------------------------
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

EMAIL_SENDER = os.environ["EMAIL_SENDER"]       # your Gmail address
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]   # Gmail App Password
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"] # where the report goes

# How many recent videos and comments per video to analyse
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def get_youtube_service():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def get_recent_video_ids(youtube, channel_id: str, max_results: int) -> list[dict]:
    """Return list of {id, title} for the most recent uploads."""
    # Get the uploads playlist for the channel
    resp = youtube.channels().list(
        part="contentDetails,snippet",
        id=channel_id
    ).execute()

    if not resp.get("items"):
        print(f"No channel found for ID: {channel_id}", file=sys.stderr)
        return []

    channel_title = resp["items"][0]["snippet"]["title"]
    uploads_playlist = resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    next_page_token = None

    while len(videos) < max_results:
        playlist_resp = youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads_playlist,
            maxResults=min(50, max_results - len(videos)),
            pageToken=next_page_token
        ).execute()

        for item in playlist_resp.get("items", []):
            videos.append({
                "id": item["contentDetails"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
            })

        next_page_token = playlist_resp.get("nextPageToken")
        if not next_page_token:
            break

    return channel_title, videos


def get_comments_for_video(youtube, video_id: str, max_results: int) -> list[dict]:
    """Return top-level comments for a video."""
    comments = []
    next_page_token = None

    try:
        while len(comments) < max_results:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_results - len(comments)),
                order="relevance",
                textFormat="plainText",
                pageToken=next_page_token
            ).execute()

            for item in resp.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "text": snippet["textDisplay"],
                    "likes": snippet["likeCount"],
                    "author": snippet["authorDisplayName"],
                })

            next_page_token = resp.get("nextPageToken")
            if not next_page_token:
                break

    except HttpError as e:
        if e.resp.status == 403:
            # Comments disabled on this video
            pass
        else:
            raise

    return comments


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def analyse_comments(channel_title: str, videos_with_comments: list[dict]) -> str:
    """Send all comment data to Claude and get a structured summary."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build a compact text block for Claude
    lines = [f"YouTube channel: {channel_title}\n"]
    for v in videos_with_comments:
        lines.append(f"\n## Video: {v['title']} (published {v['published_at'][:10]})")
        if not v["comments"]:
            lines.append("  (no comments / comments disabled)")
            continue
        for c in v["comments"]:
            lines.append(f"  [{c['likes']} likes] {c['author']}: {c['text']}")

    comments_text = "\n".join(lines)

    prompt = f"""You are analysing YouTube comments for a content creator to help them improve.

Below are recent comments across their latest videos. Please write a clear, actionable report that covers:

1. **Overall sentiment** – What is the general audience feeling? (positive / mixed / negative and why)
2. **What viewers love** – Top recurring themes of praise (be specific, quote examples)
3. **Constructive criticism & pain points** – What do viewers wish were different? Group similar complaints.
4. **Actionable improvement suggestions** – Concrete, prioritised steps the creator can take based on the feedback.
5. **Notable individual comments** – Any standout comments (very insightful, viral potential, etc.)

Keep the tone helpful and encouraging. Format using clear Markdown headings.

---

{comments_text}
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, body_html: str, body_plain: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT

    msg.attach(MIMEText(body_plain, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())


def markdown_to_html(md: str) -> str:
    """Minimal Markdown → HTML without an extra dependency."""
    import re

    html = md
    # Code blocks
    html = re.sub(r"```.*?```", lambda m: f"<pre><code>{m.group(0)[3:-3]}</code></pre>", html, flags=re.S)
    # H2
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.M)
    # H3
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.M)
    # Bold
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    # Bullet points
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.M)
    html = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", html, flags=re.S)
    # Paragraphs (double newline)
    html = re.sub(r"\n{2,}", "</p><p>", html)
    html = f"<p>{html}</p>"

    return f"""
<html><body style="font-family:sans-serif;max-width:700px;margin:auto;padding:24px">
{html}
<hr/>
<small style="color:#888">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</small>
</body></html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Connecting to YouTube API…")
    youtube = get_youtube_service()

    print(f"Fetching last {MAX_VIDEOS} videos from channel {YOUTUBE_CHANNEL_ID}…")
    channel_title, videos = get_recent_video_ids(youtube, YOUTUBE_CHANNEL_ID, MAX_VIDEOS)
    print(f"Channel: {channel_title} — {len(videos)} videos found")

    videos_with_comments = []
    for v in videos:
        print(f"  Fetching comments for: {v['title'][:60]}…")
        comments = get_comments_for_video(youtube, v["id"], MAX_COMMENTS_PER_VIDEO)
        print(f"    → {len(comments)} comments")
        videos_with_comments.append({**v, "comments": comments})

    total_comments = sum(len(v["comments"]) for v in videos_with_comments)
    print(f"\nAnalysing {total_comments} comments with Claude…")
    analysis = analyse_comments(channel_title, videos_with_comments)

    subject = f"YouTube Comment Summary — {datetime.now(timezone.utc).strftime('%B %d, %Y')}"
    print(f"Sending email to {EMAIL_RECIPIENT}…")
    send_email(subject, markdown_to_html(analysis), analysis)
    print("Done! Summary sent successfully.")


if __name__ == "__main__":
    main()
