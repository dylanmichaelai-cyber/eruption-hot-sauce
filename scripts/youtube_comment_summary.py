#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches recent comments from your YouTube channel, analyzes sentiment and
improvement suggestions using Claude, then emails a summary to you.

Required env vars:
  YOUTUBE_API_KEY   - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID - Your channel ID (e.g. UCxxxx...) — optional if
                        CHANNEL_HANDLE is set
  CHANNEL_HANDLE    - Your channel handle (e.g. @EruptionHotSauce) — used
                        to auto-resolve channel ID if YOUTUBE_CHANNEL_ID unset
  ANTHROPIC_API_KEY - Claude API key for sentiment analysis
  GMAIL_SENDER      - Gmail address to send from (must have App Password set)
  GMAIL_APP_PASSWORD - Gmail App Password (Settings > Security > App passwords)
  SUMMARY_RECIPIENT - Email address to receive the summary

Run manually:
  python3 scripts/youtube_comment_summary.py

Schedule with cron (weekly on Mondays at 8am):
  0 8 * * 1 cd /path/to/eruption-hot-sauce && python3 scripts/youtube_comment_summary.py
"""

import os
import sys
import smtplib
import textwrap
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── Configuration ─────────────────────────────────────────────────────────────

YOUTUBE_API_KEY    = os.environ.get("YOUTUBE_API_KEY", "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
CHANNEL_HANDLE     = os.environ.get("CHANNEL_HANDLE", "@EruptionHotSauce")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_SENDER       = os.environ.get("GMAIL_SENDER", "d.mcderm80@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SUMMARY_RECIPIENT  = os.environ.get("SUMMARY_RECIPIENT", "d.mcderm80@gmail.com")

MAX_VIDEOS   = 10   # how many recent videos to pull comments from
MAX_COMMENTS = 300  # total comment cap (to stay within Claude context)

# ── YouTube helpers ───────────────────────────────────────────────────────────

def get_youtube_client():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def resolve_channel_id(yt) -> str:
    if YOUTUBE_CHANNEL_ID:
        return YOUTUBE_CHANNEL_ID

    # Try resolving via handle search
    resp = yt.search().list(
        part="snippet",
        q=CHANNEL_HANDLE,
        type="channel",
        maxResults=1,
    ).execute()

    items = resp.get("items", [])
    if not items:
        sys.exit(f"Could not find channel for handle '{CHANNEL_HANDLE}'. "
                 "Set YOUTUBE_CHANNEL_ID directly.")
    channel_id = items[0]["id"]["channelId"]
    print(f"Resolved channel ID: {channel_id}")
    return channel_id


def get_recent_video_ids(yt, channel_id: str) -> list[dict]:
    """Return list of {id, title} for the most recent videos."""
    resp = yt.search().list(
        part="snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=MAX_VIDEOS,
    ).execute()

    return [
        {"id": item["id"]["videoId"], "title": item["snippet"]["title"]}
        for item in resp.get("items", [])
    ]


def get_comments_for_video(yt, video_id: str, max_per_video: int = 50) -> list[str]:
    """Return top-level comment texts for a single video."""
    comments = []
    try:
        request = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_per_video, 100),
            textFormat="plainText",
            order="relevance",
        )
        while request and len(comments) < max_per_video:
            resp = request.execute()
            for item in resp.get("items", []):
                text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                comments.append(text.strip())
            request = yt.commentThreads().list_next(request, resp)
    except HttpError as e:
        if e.resp.status == 403:
            print(f"  Comments disabled for video {video_id}, skipping.")
        else:
            print(f"  Error fetching comments for {video_id}: {e}")
    return comments


def fetch_all_comments(yt, channel_id: str) -> tuple[list[dict], list[str]]:
    """Fetch comments across recent videos. Returns (videos, all_comments)."""
    videos = get_recent_video_ids(yt, channel_id)
    if not videos:
        sys.exit("No videos found on this channel.")

    per_video_cap = max(10, MAX_COMMENTS // len(videos))
    all_comments = []

    for v in videos:
        print(f"Fetching comments for: {v['title'][:60]}")
        comments = get_comments_for_video(yt, v["id"], per_video_cap)
        all_comments.extend(comments)
        if len(all_comments) >= MAX_COMMENTS:
            all_comments = all_comments[:MAX_COMMENTS]
            break

    return videos, all_comments


# ── Claude analysis ───────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are a content strategist analyzing YouTube comments for a hot sauce brand
called Eruption Hot Sauce. Below are {n} viewer comments collected from the
channel's {v} most recent videos.

Your task:
1. **Overall Sentiment** – What is the general mood of viewers? (positive /
   mixed / negative, with a brief explanation and any % breakdown if clear.)
2. **What viewers LOVE** – Top 3–5 themes with supporting quotes.
3. **What viewers want IMPROVED** – Top 3–5 constructive issues or requests,
   with supporting quotes.
4. **Actionable Recommendations** – Specific, prioritized suggestions the
   creator should act on next.
5. **Standout Comments** – 2–3 comments worth replying to or highlighting.

Be direct and specific. Use bullet points. Quote comments exactly when useful.

--- COMMENTS START ---
{comments}
--- COMMENTS END ---
"""


def analyze_with_claude(videos: list[dict], comments: list[str]) -> str:
    if not ANTHROPIC_API_KEY:
        sys.exit("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    comments_block = "\n".join(f"- {c}" for c in comments)

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": ANALYSIS_PROMPT.format(
                    n=len(comments),
                    v=len(videos),
                    comments=comments_block,
                ),
            }
        ],
    )
    return message.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def build_email_html(analysis: str, videos: list[dict], comment_count: int) -> str:
    video_list = "".join(
        f'<li><a href="https://www.youtube.com/watch?v={v["id"]}">{v["title"]}</a></li>'
        for v in videos
    )
    analysis_html = "<br>".join(
        line if line.strip() else "<br>"
        for line in analysis.splitlines()
    )
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    return f"""
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 700px; margin: auto; color: #222; }}
  h1 {{ color: #c0392b; }}
  h2 {{ color: #c0392b; border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  .meta {{ color: #666; font-size: 0.9em; margin-bottom: 24px; }}
  .analysis {{ line-height: 1.7; white-space: pre-wrap; }}
  ul {{ padding-left: 1.2em; }}
  footer {{ margin-top: 32px; font-size: 0.8em; color: #aaa; }}
</style>
</head>
<body>
<h1>🌶️ Eruption Hot Sauce — YouTube Comment Summary</h1>
<p class="meta">
  Generated: {date_str} &nbsp;|&nbsp;
  Videos analyzed: {len(videos)} &nbsp;|&nbsp;
  Comments analyzed: {comment_count}
</p>

<h2>Videos Covered</h2>
<ul>{video_list}</ul>

<h2>Analysis</h2>
<div class="analysis">{analysis_html}</div>

<footer>
  This summary was generated automatically by your YouTube comment routine.<br>
  Powered by YouTube Data API v3 + Claude.
</footer>
</body>
</html>
"""


def send_email(subject: str, html_body: str, plain_body: str):
    if not GMAIL_APP_PASSWORD:
        print("\n--- EMAIL PREVIEW (GMAIL_APP_PASSWORD not set) ---")
        print(plain_body)
        print("--------------------------------------------------")
        print("Set GMAIL_APP_PASSWORD to enable actual sending.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_SENDER
    msg["To"] = SUMMARY_RECIPIENT
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, SUMMARY_RECIPIENT, msg.as_string())

    print(f"Email sent to {SUMMARY_RECIPIENT}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Eruption Hot Sauce — YouTube Comment Summary ===\n")

    print("Connecting to YouTube API...")
    yt = get_youtube_client()

    channel_id = resolve_channel_id(yt)

    print(f"Fetching up to {MAX_VIDEOS} recent videos...\n")
    videos, comments = fetch_all_comments(yt, channel_id)

    print(f"\nCollected {len(comments)} comments from {len(videos)} videos.")

    if not comments:
        sys.exit("No comments found. Nothing to analyze.")

    print("\nSending to Claude for analysis...")
    analysis = analyze_with_claude(videos, comments)

    subject = f"YouTube Comment Summary — {datetime.now(timezone.utc).strftime('%B %d, %Y')}"
    html_body = build_email_html(analysis, videos, len(comments))
    plain_body = textwrap.dedent(f"""\
        Eruption Hot Sauce — YouTube Comment Summary
        Generated: {datetime.now(timezone.utc).strftime('%B %d, %Y')}
        Videos: {len(videos)} | Comments: {len(comments)}

        {analysis}
    """)

    print("Sending email summary...")
    send_email(subject, html_body, plain_body)

    print("\nDone!")


if __name__ == "__main__":
    main()
