#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
================================
Fetches comments from your YouTube channel's recent videos,
analyzes audience sentiment with Claude, and emails you a summary
with actionable improvement suggestions.

SETUP:
  1. Copy .env.example to .env and fill in your values
  2. pip install -r requirements.txt
  3. python3 youtube_comment_summary.py

SCHEDULE (cron example — runs every Monday at 8am):
  0 8 * * 1 cd /path/to/project && python3 youtube_comment_summary.py >> youtube_routine.log 2>&1
"""

import os
import re
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import anthropic


# ── Load .env file if it exists ───────────────────────────────────────────────

def load_dotenv(env_path=".env"):
    path = Path(env_path)
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


# ── Configuration ─────────────────────────────────────────────────────────────

YOUTUBE_API_KEY        = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID     = os.environ.get("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "")  # e.g. @DylanAutomates
ANTHROPIC_API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_FROM             = os.environ.get("EMAIL_FROM", "")
EMAIL_TO               = os.environ.get("EMAIL_TO", "")
EMAIL_APP_PASSWORD     = os.environ.get("EMAIL_APP_PASSWORD", "")
MAX_VIDEOS             = int(os.environ.get("MAX_VIDEOS", "8"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))


# ── Validation ────────────────────────────────────────────────────────────────

def validate_config():
    errors = []
    if not YOUTUBE_API_KEY:
        errors.append("YOUTUBE_API_KEY is required")
    if not YOUTUBE_CHANNEL_ID and not YOUTUBE_CHANNEL_HANDLE:
        errors.append("Either YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE is required")
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is required (get one at console.anthropic.com)")
    if not EMAIL_FROM:
        errors.append("EMAIL_FROM is required (your Gmail address)")
    if not EMAIL_TO:
        errors.append("EMAIL_TO is required (where to send the summary)")
    if not EMAIL_APP_PASSWORD:
        errors.append("EMAIL_APP_PASSWORD is required (Gmail app password, not your login password)")
    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  • {e}")
        print("\nCopy .env.example to .env and fill in your values.")
        sys.exit(1)


# ── YouTube helpers ───────────────────────────────────────────────────────────

def resolve_channel_id(youtube, channel_id: str, handle: str) -> str:
    """Return the channel ID, resolving a handle if needed."""
    if channel_id:
        return channel_id
    # Strip leading @ if present
    handle_clean = handle.lstrip("@")
    resp = youtube.channels().list(
        part="id,snippet",
        forHandle=handle_clean,
    ).execute()
    items = resp.get("items", [])
    if not items:
        print(f"Could not find channel for handle @{handle_clean}. Check YOUTUBE_CHANNEL_HANDLE.")
        sys.exit(1)
    resolved = items[0]["id"]
    print(f"Resolved @{handle_clean} → channel ID: {resolved}")
    return resolved


def get_recent_videos(youtube, channel_id: str, max_videos: int) -> list[dict]:
    """Return the most recent videos from a channel."""
    resp = youtube.search().list(
        part="id,snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=max_videos,
    ).execute()
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
        }
        for item in resp.get("items", [])
    ]


def get_video_comments(youtube, video_id: str, max_comments: int) -> list[dict]:
    """Return top-level comments for a video, sorted by relevance."""
    try:
        resp = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_comments, 100),
            order="relevance",
        ).execute()
        comments = []
        for item in resp.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": snippet["textDisplay"],
                "author": snippet["authorDisplayName"],
                "likes": snippet["likeCount"],
            })
        return comments
    except HttpError as e:
        if e.resp.status == 403:
            print(f"  Comments disabled for video {video_id}, skipping.")
        else:
            print(f"  Error fetching comments for {video_id}: {e}")
        return []


# ── Claude analysis ───────────────────────────────────────────────────────────

def build_comment_block(videos_with_comments: list[dict]) -> str:
    lines = []
    for video in videos_with_comments:
        lines.append(f"### {video['title']} ({video['published_at']}, {len(video['comments'])} comments)")
        if video["comments"]:
            for c in video["comments"][:30]:
                text = re.sub(r"<[^>]+>", "", c["text"])[:200]  # strip HTML tags
                lines.append(f"  [{c['likes']}♥] {text}")
        else:
            lines.append("  (no comments or comments disabled)")
        lines.append("")
    return "\n".join(lines)


def analyze_with_claude(client: anthropic.Anthropic, comment_block: str) -> str:
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": (
                    "Below are comments from my YouTube channel's recent videos. "
                    "Analyze them and give me a structured report.\n\n"
                    f"{comment_block}\n\n"
                    "Please provide:\n"
                    "1. **Overall Sentiment** — positive/negative/mixed ratio and the general vibe\n"
                    "2. **What Viewers Love** — specific things getting the most praise\n"
                    "3. **Common Criticism** — recurring complaints or disappointments\n"
                    "4. **Top 5 Improvement Actions** — concrete, prioritized things I can do better\n"
                    "5. **Video Ideas from Comments** — topics or questions viewers keep asking for\n\n"
                    "Be direct and specific. Skip generic advice. Base everything on what's actually in the comments."
                ),
            }
        ],
    )
    return msg.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

_HTML_STRONG_RE = re.compile(r"\*\*(.+?)\*\*")
_HTML_H3_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def _to_html(text: str) -> str:
    text = _HTML_STRONG_RE.sub(r"<strong>\1</strong>", text)
    text = _HTML_H3_RE.sub(r"<h3>\1</h3>", text)
    text = text.replace("\n", "<br>")
    return text


def send_summary_email(
    videos_with_comments: list[dict],
    analysis: str,
    date_str: str,
):
    total_comments = sum(len(v["comments"]) for v in videos_with_comments)
    subject = f"YouTube Comment Summary — {date_str}"

    video_list_text = "\n".join(
        f"  • {v['title'][:65]} ({len(v['comments'])} comments)" for v in videos_with_comments
    )
    plain = (
        f"YouTube Comment Summary — {date_str}\n"
        f"{'=' * 50}\n\n"
        f"Analyzed {total_comments} comments across {len(videos_with_comments)} videos.\n\n"
        f"VIDEOS:\n{video_list_text}\n\n"
        f"ANALYSIS:\n{analysis}\n\n"
        "---\nYouTube Comment Summary Routine\n"
    )

    video_list_html = "".join(
        f"<li><strong>{v['title'][:70]}</strong> "
        f"<span style='color:#888'>({len(v['comments'])} comments · {v['published_at']})</span></li>"
        for v in videos_with_comments
    )
    html = f"""
<html>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:24px;color:#222">
  <h2 style="color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:8px">
    🎥 YouTube Comment Summary<br>
    <span style="font-size:14px;font-weight:normal;color:#666">{date_str}</span>
  </h2>

  <p style="color:#555">
    Analyzed <strong>{total_comments} comments</strong> across
    <strong>{len(videos_with_comments)} videos</strong>.
  </p>

  <h3 style="color:#333">Videos Analyzed</h3>
  <ul style="line-height:1.8">{video_list_html}</ul>

  <h3 style="color:#333">Claude's Analysis</h3>
  <div style="background:#f7f7f7;border-left:4px solid #cc0000;padding:16px 20px;
              border-radius:0 4px 4px 0;line-height:1.7">
    {_to_html(analysis)}
  </div>

  <hr style="border:none;border-top:1px solid #eee;margin-top:32px">
  <p style="color:#aaa;font-size:12px">YouTube Comment Summary Routine</p>
</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    validate_config()

    now = datetime.now()
    date_str = now.strftime("%B %d, %Y")
    log = lambda msg: print(f"[{now.strftime('%H:%M:%S')}] {msg}", flush=True)

    log("Building YouTube client…")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    channel_id = resolve_channel_id(youtube, YOUTUBE_CHANNEL_ID, YOUTUBE_CHANNEL_HANDLE)

    log(f"Fetching last {MAX_VIDEOS} videos…")
    videos = get_recent_videos(youtube, channel_id, MAX_VIDEOS)
    if not videos:
        log("No videos found. Verify your channel ID or handle and try again.")
        sys.exit(1)
    log(f"Found {len(videos)} videos.")

    log("Fetching comments…")
    videos_with_comments = []
    for v in videos:
        log(f"  ↳ {v['title'][:60]}…")
        comments = get_video_comments(youtube, v["video_id"], MAX_COMMENTS_PER_VIDEO)
        videos_with_comments.append({**v, "comments": comments})

    total = sum(len(v["comments"]) for v in videos_with_comments)
    log(f"Fetched {total} comments total. Sending to Claude for analysis…")

    comment_block = build_comment_block(videos_with_comments)
    analysis = analyze_with_claude(claude, comment_block)

    log(f"Sending summary email to {EMAIL_TO}…")
    send_summary_email(videos_with_comments, analysis, date_str)
    log("Done. Email sent successfully.")


if __name__ == "__main__":
    main()
