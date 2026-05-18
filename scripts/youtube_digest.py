#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel, analyses sentiment
and improvement suggestions with Claude, then emails you a digest.

Setup:
  1. Copy ../.env.example to ../.env and fill in your values.
  2. pip install -r requirements.txt
  3. python youtube_digest.py          # run once
  4. Add to cron for a recurring digest, e.g. every Monday at 8 am:
       0 8 * * 1 /usr/bin/python3 /path/to/youtube_digest.py
"""

import os
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Config (all values come from .env) ────────────────────────────────────────

YOUTUBE_API_KEY   = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID        = os.environ["YOUTUBE_CHANNEL_ID"]   # e.g. UCxxxxxxxxxxxxxx
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

EMAIL_FROM        = os.environ["EMAIL_FROM"]           # your sending address
EMAIL_TO          = os.environ["EMAIL_TO"]             # where the digest goes
SMTP_HOST         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER         = os.environ["SMTP_USER"]
SMTP_PASSWORD     = os.environ["SMTP_PASSWORD"]        # for Gmail: use an App Password

# How many days back to pull comments (default: last 7 days)
LOOKBACK_DAYS     = int(os.environ.get("LOOKBACK_DAYS", "7"))
# Max comments to analyse per run (keeps Claude costs manageable)
MAX_COMMENTS      = int(os.environ.get("MAX_COMMENTS", "200"))


# ── YouTube helpers ───────────────────────────────────────────────────────────

def youtube_client():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def get_channel_videos(yt, channel_id: str, published_after: str) -> list[dict]:
    """Return videos uploaded to the channel after published_after (RFC 3339)."""
    videos = []
    page_token = None
    while True:
        resp = yt.search().list(
            part="id,snippet",
            channelId=channel_id,
            type="video",
            publishedAfter=published_after,
            maxResults=50,
            pageToken=page_token,
            order="date",
        ).execute()
        for item in resp.get("items", []):
            videos.append({
                "video_id": item["id"]["videoId"],
                "title":    item["snippet"]["title"],
                "published": item["snippet"]["publishedAt"],
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return videos


def get_all_videos(yt, channel_id: str) -> list[dict]:
    """Return all videos for the channel (no date filter) — used as fallback."""
    videos = []
    # Get uploads playlist id
    ch = yt.channels().list(part="contentDetails", id=channel_id).execute()
    uploads_id = (
        ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )
    page_token = None
    while len(videos) < 50:          # cap at 50 videos for the fallback path
        resp = yt.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp.get("items", []):
            videos.append({
                "video_id": item["snippet"]["resourceId"]["videoId"],
                "title":    item["snippet"]["title"],
                "published": item["snippet"]["publishedAt"],
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return videos


def fetch_comments(yt, video: dict, cutoff_dt: datetime) -> list[dict]:
    """Fetch top-level comments for a video published after cutoff_dt."""
    comments = []
    page_token = None
    try:
        while True:
            resp = yt.commentThreads().list(
                part="snippet",
                videoId=video["video_id"],
                maxResults=100,
                pageToken=page_token,
                order="relevance",
                textFormat="plainText",
            ).execute()
            for item in resp.get("items", []):
                snip = item["snippet"]["topLevelComment"]["snippet"]
                published = datetime.fromisoformat(
                    snip["publishedAt"].replace("Z", "+00:00")
                )
                if published < cutoff_dt:
                    continue
                comments.append({
                    "video_title": video["title"],
                    "video_id":    video["video_id"],
                    "author":      snip["authorDisplayName"],
                    "text":        snip["textDisplay"],
                    "likes":       snip["likeCount"],
                    "published":   snip["publishedAt"],
                })
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        print(f"  ⚠ Skipping {video['video_id']}: {exc}", file=sys.stderr)
    return comments


# ── Analysis ─────────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are an expert YouTube content analyst. Below are recent comments left on a
creator's YouTube videos. Analyse them and produce a concise digest with three
sections:

1. **Overall Sentiment** – a short paragraph describing how viewers feel.
   Include approximate positive / neutral / negative breakdown if clear.

2. **What viewers love** – bullet list of specific things people praise.

3. **Improvement suggestions** – bullet list of concrete, actionable things the
   creator could do better, backed by what commenters actually said.
   Prioritise by how frequently a theme appears.

Keep the whole response under 600 words. Be direct and specific.

---
COMMENTS ({count} total, from the past {days} days):

{comments_text}
"""


def analyse_comments(comments: list[dict], days: int) -> str:
    comments_text = "\n\n".join(
        f"[{c['video_title']}] {c['author']}: {c['text']}"
        for c in comments
    )
    prompt = ANALYSIS_PROMPT.format(
        count=len(comments),
        days=days,
        comments_text=comments_text,
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def build_email(analysis: str, comments: list[dict], days: int) -> MIMEMultipart:
    subject = (
        f"YouTube Comment Digest — {datetime.now().strftime('%b %d, %Y')} "
        f"({len(comments)} comments, last {days} days)"
    )

    # Group by video for the stats table
    by_video: dict[str, list] = {}
    for c in comments:
        by_video.setdefault(c["video_title"], []).append(c)

    stats_rows = "\n".join(
        f"  • {title}: {len(cmts)} comment(s)"
        for title, cmts in sorted(by_video.items(), key=lambda x: -len(x[1]))
    )

    body_text = f"""\
YouTube Comment Digest
======================
Period : last {days} days
Videos : {len(by_video)}
Comments analysed: {len(comments)}

{stats_rows}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{analysis}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOP COMMENTS (by likes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""" + "\n\n".join(
        f'[{c["video_title"]}] 👍 {c["likes"]}  @{c["author"]}\n{c["text"]}'
        for c in sorted(comments, key=lambda x: -x["likes"])[:20]
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body_text, "plain"))
    return msg


def send_email(msg: MIMEMultipart) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    published_after = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"Fetching videos published after {published_after} …")
    yt = youtube_client()

    videos = get_channel_videos(yt, CHANNEL_ID, published_after)
    if not videos:
        print("No new videos in the lookback window — fetching all channel videos instead.")
        videos = get_all_videos(yt, CHANNEL_ID)

    print(f"Found {len(videos)} video(s). Fetching comments …")
    all_comments: list[dict] = []
    for v in videos:
        print(f"  → {v['title']}")
        cmts = fetch_comments(yt, v, cutoff_dt)
        all_comments.extend(cmts)
        if len(all_comments) >= MAX_COMMENTS:
            all_comments = all_comments[:MAX_COMMENTS]
            break

    if not all_comments:
        print("No comments found in this period. Exiting.")
        return

    print(f"Analysing {len(all_comments)} comment(s) with Claude …")
    analysis = analyse_comments(all_comments, LOOKBACK_DAYS)

    print("Sending digest email …")
    msg = build_email(analysis, all_comments, LOOKBACK_DAYS)
    send_email(msg)
    print(f"Done! Digest sent to {EMAIL_TO}.")


if __name__ == "__main__":
    main()
