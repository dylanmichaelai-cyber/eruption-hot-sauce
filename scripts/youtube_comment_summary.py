#!/usr/bin/env python3
"""
Fetches recent YouTube comments across your channel's videos,
analyzes sentiment and improvement areas with Claude,
then emails you a digest.

Required env vars:
  YOUTUBE_API_KEY       — YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID    — Your channel ID (starts with UC…)
  ANTHROPIC_API_KEY     — Anthropic API key
  EMAIL_FROM            — Gmail address to send from
  EMAIL_TO              — Address to receive the summary
  EMAIL_APP_PASSWORD    — Gmail App Password (not your account password)

Optional:
  VIDEOS_TO_CHECK       — How many recent videos to scan (default: 5)
  COMMENTS_PER_VIDEO    — Max comments per video (default: 100)
"""

import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── Config ────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY    = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID         = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
EMAIL_FROM         = os.environ["EMAIL_FROM"]
EMAIL_TO           = os.environ["EMAIL_TO"]
EMAIL_APP_PASSWORD = os.environ["EMAIL_APP_PASSWORD"]

VIDEOS_TO_CHECK    = int(os.environ.get("VIDEOS_TO_CHECK", 5))
COMMENTS_PER_VIDEO = int(os.environ.get("COMMENTS_PER_VIDEO", 100))

# ── YouTube helpers ───────────────────────────────────────────────────────────

def get_recent_videos(youtube):
    """Return a list of (video_id, title, published_at) for recent uploads."""
    # Resolve the uploads playlist for the channel
    chan = youtube.channels().list(
        part="contentDetails,snippet",
        id=CHANNEL_ID,
    ).execute()

    if not chan["items"]:
        sys.exit(f"Channel {CHANNEL_ID!r} not found. Check YOUTUBE_CHANNEL_ID.")

    channel_title    = chan["items"][0]["snippet"]["title"]
    uploads_playlist = chan["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Walk the uploads playlist
    videos, page_token = [], None
    while len(videos) < VIDEOS_TO_CHECK:
        resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist,
            maxResults=min(VIDEOS_TO_CHECK - len(videos), 50),
            pageToken=page_token,
        ).execute()

        for item in resp["items"]:
            snip = item["snippet"]
            videos.append({
                "id":           snip["resourceId"]["videoId"],
                "title":        snip["title"],
                "published_at": snip["publishedAt"],
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return channel_title, videos


def get_comments(youtube, video_id):
    """Return a flat list of top-level comment strings for a video."""
    comments, page_token = [], None
    try:
        while len(comments) < COMMENTS_PER_VIDEO:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(COMMENTS_PER_VIDEO - len(comments), 100),
                order="relevance",
                textFormat="plainText",
                pageToken=page_token,
            ).execute()

            for item in resp["items"]:
                text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                comments.append(text)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    except HttpError as e:
        # Comments can be disabled on a video — skip gracefully
        if e.resp.status == 403:
            return []
        raise

    return comments

# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze_with_claude(channel_title, videos_with_comments):
    """Use Claude to produce a structured sentiment + improvement digest."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the input block — one section per video
    sections = []
    for v in videos_with_comments:
        if not v["comments"]:
            sections.append(
                f'### "{v["title"]}"\n(Comments are disabled or none exist)'
            )
            continue
        comment_block = "\n".join(f"- {c}" for c in v["comments"][:100])
        sections.append(f'### "{v["title"]}"\n{comment_block}')

    combined = "\n\n".join(sections)

    prompt = f"""You are analyzing YouTube comments for the channel **{channel_title}**.

Below are comments collected from the {len(videos_with_comments)} most recent videos.

{combined}

Please write a concise, actionable digest with these sections:

1. **Overall Sentiment** — A 2-3 sentence summary of the general mood across all videos.
2. **What Viewers Love** — The top 3-5 things people respond to most positively (with brief evidence from comments).
3. **Common Criticisms or Questions** — Recurring complaints, confusions, or requests.
4. **Improvement Suggestions** — 4-6 concrete, prioritized recommendations the creator can act on.
5. **Video-by-Video Highlights** — One bullet per video: dominant sentiment + standout comment (paraphrased).

Be direct and specific. Skip generic advice. Focus on patterns unique to these comments."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject, body_text):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    # Plain-text part
    msg.attach(MIMEText(body_text, "plain"))

    # Simple HTML wrapper for readability
    html_body = body_text.replace("\n", "<br>").replace("**", "")
    html = f"""<html><body style="font-family:sans-serif;max-width:700px;margin:auto;padding:20px">
<h2 style="color:#c0392b">YouTube Comment Digest</h2>
{html_body}
<hr><p style="font-size:12px;color:#888">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Building YouTube client…")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching {VIDEOS_TO_CHECK} most recent videos…")
    channel_title, videos = get_recent_videos(youtube)
    print(f"Channel: {channel_title}")

    videos_with_comments = []
    for v in videos:
        print(f"  Fetching comments for: {v['title'][:60]}")
        comments = get_comments(youtube, v["id"])
        print(f"    → {len(comments)} comment(s)")
        videos_with_comments.append({**v, "comments": comments})

    total = sum(len(v["comments"]) for v in videos_with_comments)
    print(f"\nAnalyzing {total} total comments with Claude…")
    analysis = analyze_with_claude(channel_title, videos_with_comments)

    subject = f"YouTube Digest — {channel_title} ({datetime.now().strftime('%b %d, %Y')})"
    print(f"\nSending email to {EMAIL_TO}…")
    send_email(subject, analysis)
    print("Done.")


if __name__ == "__main__":
    main()
