#!/usr/bin/env python3
"""
YouTube Comments Digest
Fetches recent comments from your YouTube channel, analyzes sentiment
with Claude, and emails you a summary of feedback and improvement ideas.

Required env vars:
  YOUTUBE_API_KEY      - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID   - Your YouTube channel ID (see README for how to find it)
  ANTHROPIC_API_KEY    - Anthropic API key for Claude summarization
  EMAIL_SENDER         - Gmail address to send FROM
  EMAIL_APP_PASSWORD   - Gmail App Password (not your login password)
  EMAIL_RECIPIENT      - Address to send the digest TO
"""

import os
import sys
import smtplib
import textwrap
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY    = os.environ.get("YOUTUBE_API_KEY")
CHANNEL_ID         = os.environ.get("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY")
EMAIL_SENDER       = os.environ.get("EMAIL_SENDER")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")
EMAIL_RECIPIENT    = os.environ.get("EMAIL_RECIPIENT")

# How many recent videos to scan and max comments per video
MAX_VIDEOS         = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER   = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))
# Only include comments newer than this many days (0 = all time)
DAYS_LOOKBACK      = int(os.environ.get("DAYS_LOOKBACK", "30"))

YT_BASE = "https://www.googleapis.com/youtube/v3"

# ── YouTube helpers ───────────────────────────────────────────────────────────

def yt_get(endpoint, **params):
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_recent_videos(channel_id, max_results):
    """Return list of {id, title, published_at} for the channel's recent uploads."""
    # Resolve the uploads playlist ID
    data = yt_get("channels", id=channel_id, part="contentDetails,snippet")
    items = data.get("items", [])
    if not items:
        raise ValueError(f"Channel not found or no access: {channel_id}")

    channel_title = items[0]["snippet"]["title"]
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Walk the uploads playlist
    videos = []
    page_token = None
    while len(videos) < max_results:
        kwargs = dict(playlistId=uploads_playlist, part="snippet", maxResults=min(50, max_results))
        if page_token:
            kwargs["pageToken"] = page_token
        page = yt_get("playlistItems", **kwargs)
        for item in page.get("items", []):
            snip = item["snippet"]
            videos.append({
                "id":           snip["resourceId"]["videoId"],
                "title":        snip["title"],
                "published_at": snip["publishedAt"],
            })
        page_token = page.get("nextPageToken")
        if not page_token or len(videos) >= max_results:
            break

    return channel_title, videos[:max_results]


def fetch_comments(video_id, max_results, since_dt=None):
    """Return list of comment strings for a video."""
    comments = []
    page_token = None
    while len(comments) < max_results:
        kwargs = dict(
            videoId=video_id,
            part="snippet",
            maxResults=min(100, max_results),
            order="relevance",
            textFormat="plainText",
        )
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            page = yt_get("commentThreads", **kwargs)
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                # Comments disabled on this video
                return []
            raise

        for item in page.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            published = top["publishedAt"]
            if since_dt:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub_dt < since_dt:
                    continue
            comments.append(top["textDisplay"])

        page_token = page.get("nextPageToken")
        if not page_token or len(comments) >= max_results:
            break

    return comments[:max_results]


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyse_comments(channel_title, video_comment_pairs):
    """Use Claude to produce a structured digest from all collected comments."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the comment dump
    sections = []
    for video_title, comments in video_comment_pairs:
        if not comments:
            continue
        block = f"### {video_title}\n" + "\n".join(f"- {c}" for c in comments)
        sections.append(block)

    if not sections:
        return "No comments were found in the specified time window."

    comment_dump = "\n\n".join(sections)

    prompt = textwrap.dedent(f"""
        You are analyzing YouTube comments for the channel "{channel_title}".
        Below are comments grouped by video title.

        {comment_dump}

        Please produce a concise email digest with these sections:

        ## Overall Sentiment
        One paragraph summarising whether the audience is positive, mixed, or negative overall,
        and what the dominant emotional tone is.

        ## What Viewers Love
        Bullet list of specific things viewers praise or respond positively to (themes, segments,
        style, personality, content type, etc.). Include short example quotes where relevant.

        ## Constructive Feedback & Improvement Areas
        Bullet list of recurring complaints, requests, or suggestions. Be specific — general
        statements like "better quality" are less useful than "viewers want longer taste-test
        segments" or "audio levels spike on close-up shots".

        ## Top Action Items
        Numbered list of 3–5 concrete, prioritised things you could do next to improve engagement
        and viewer satisfaction, based solely on the comments.

        ## Standout Comments
        2–3 quotes that are especially insightful, funny, or worth reading verbatim.

        Keep the tone professional but friendly. Be direct — no filler phrases.
    """).strip()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject, body_text):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT

    # Plain text part
    msg.attach(MIMEText(body_text, "plain"))

    # Simple HTML version (convert markdown-ish headers to bold)
    html_body = body_text.replace("\n## ", "\n<h2>").replace("\n### ", "\n<h3>")
    html_body = f"<pre style='font-family:sans-serif;white-space:pre-wrap'>{html_body}</pre>"
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

    print(f"  Email sent to {EMAIL_RECIPIENT}")


# ── Validation ────────────────────────────────────────────────────────────────

def check_env():
    missing = [
        name for name, val in {
            "YOUTUBE_API_KEY":    YOUTUBE_API_KEY,
            "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
            "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
            "EMAIL_SENDER":       EMAIL_SENDER,
            "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
            "EMAIL_RECIPIENT":    EMAIL_RECIPIENT,
        }.items() if not val
    ]
    if missing:
        print("ERROR: Missing required environment variables:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    check_env()

    since_dt = None
    if DAYS_LOOKBACK > 0:
        since_dt = datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)
        window_label = f"last {DAYS_LOOKBACK} days"
    else:
        window_label = "all time"

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {CHANNEL_ID}...")
    channel_title, videos = fetch_recent_videos(CHANNEL_ID, MAX_VIDEOS)
    print(f"  Channel: {channel_title}  ({len(videos)} videos found)")

    video_comment_pairs = []
    total_comments = 0
    for v in videos:
        print(f"  Fetching comments for: {v['title'][:60]}...")
        comments = fetch_comments(v["id"], MAX_COMMENTS_PER, since_dt)
        video_comment_pairs.append((v["title"], comments))
        total_comments += len(comments)
        print(f"    {len(comments)} comment(s) collected")

    print(f"\nTotal comments collected ({window_label}): {total_comments}")

    if total_comments == 0:
        print("No comments to analyse. Nothing to send.")
        return

    print("Analysing with Claude...")
    digest = analyse_comments(channel_title, video_comment_pairs)

    date_str = datetime.now().strftime("%B %d, %Y")
    subject  = f"YouTube Comment Digest — {channel_title} ({date_str})"
    body = (
        f"YouTube Comment Digest\n"
        f"{channel_title} · {date_str} · {window_label}\n"
        f"Videos scanned: {len(videos)}  |  Comments analysed: {total_comments}\n"
        f"{'─' * 60}\n\n"
        f"{digest}\n"
    )

    print("Sending email...")
    send_email(subject, body)
    print("Done.")


if __name__ == "__main__":
    main()
