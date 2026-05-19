#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches comments from your YouTube channel, analyzes sentiment with Claude,
and emails you a summary of what viewers love and what to improve.

Usage:
    python digest.py [--days N] [--channel CHANNEL_ID]

Config is loaded from .env in this directory or environment variables.
"""

import os
import sys
import argparse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # dotenv optional; fall back to env vars

# ── Config ──────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY", "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
CHANNEL_ID        = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_USER        = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
TO_EMAIL          = os.environ.get("TO_EMAIL", "")
DAYS_BACK         = int(os.environ.get("DAYS_BACK", "7"))
MAX_COMMENTS      = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "75"))
# ────────────────────────────────────────────────────────────────────────────


def fetch_recent_videos(youtube, channel_id: str, days_back: int) -> list[dict]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    videos, next_page = [], None
    while True:
        resp = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            publishedAfter=published_after,
            type="video",
            order="date",
            maxResults=50,
            pageToken=next_page,
        ).execute()

        for item in resp.get("items", []):
            videos.append({
                "id":    item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
            })

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    return videos


def fetch_comments(youtube, video_id: str, max_results: int) -> list[dict]:
    comments, next_page = [], None
    try:
        while len(comments) < max_results:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_results - len(comments)),
                textFormat="plainText",
                order="relevance",
                pageToken=next_page,
            ).execute()

            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "text":   top["textDisplay"],
                    "likes":  top.get("likeCount", 0),
                    "author": top["authorDisplayName"],
                })

            next_page = resp.get("nextPageToken")
            if not next_page:
                break
    except Exception as exc:
        print(f"  [warn] comments disabled or error on {video_id}: {exc}")

    return comments


def analyze_video(client, video_title: str, comments: list[dict]) -> str | None:
    if not comments:
        return None

    block = "\n".join(
        f"[{c['likes']} likes] {c['text']}" for c in comments[:MAX_COMMENTS]
    )

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=900,
        messages=[{
            "role": "user",
            "content": (
                f'Analyze the YouTube comments below for the video "{video_title}".\n\n'
                f"{block}\n\n"
                "Return exactly these five sections:\n"
                "**Overall Sentiment** – positive/mixed/negative + one-sentence vibe.\n"
                "**What viewers love** – top 3 bullet points.\n"
                "**Improvement suggestions** – top 3-5 specific, actionable bullets.\n"
                "**Recurring themes / questions** – 2-3 bullets.\n"
                "**Standout comment** – one quote that sums up the crowd.\n"
                "Be concise and direct."
            ),
        }],
    )
    return msg.content[0].text


def overall_summary(client, analyses: list[tuple[str, str]]) -> str:
    combined = "\n\n---\n\n".join(
        f"Video: {title}\n{analysis}" for title, analysis in analyses
    )
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": (
                "Based on these per-video comment analyses, write a 3-5 sentence "
                "executive summary covering: overall channel sentiment, the single most "
                "impactful improvement to make, and one encouraging trend.\n\n"
                f"{combined}"
            ),
        }],
    )
    return msg.content[0].text


# ── Email builder ────────────────────────────────────────────────────────────

def _markdown_to_simple_html(text: str) -> str:
    """Convert **bold** markers and bullet lines to basic HTML."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    lines, out = text.split("\n"), []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("• "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if stripped:
                out.append(f"<p>{stripped}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def build_email(
    analyses: list[tuple[str, str]],
    summary: str,
    days_back: int,
    total_comments: int,
) -> tuple[str, str]:
    date_str = datetime.now().strftime("%B %d, %Y")
    subject  = f"YouTube Comment Digest — {date_str}"

    video_cards = ""
    for title, analysis in analyses:
        if analysis:
            body_html = _markdown_to_simple_html(analysis)
            video_cards += f"""
            <div style="margin-bottom:28px;padding:20px 24px;background:#fafafa;
                        border-radius:8px;border-left:4px solid #ff4500;">
              <h3 style="margin:0 0 12px;color:#222;font-size:16px;">{title}</h3>
              <div style="color:#444;font-size:14px;line-height:1.7;">{body_html}</div>
            </div>"""

    summary_html = _markdown_to_simple_html(summary)

    html = f"""<!DOCTYPE html>
<html lang="en">
<body style="font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:0 auto;
             padding:24px;color:#222;background:#fff;">

  <div style="background:linear-gradient(135deg,#ff4500,#ff8c00);padding:28px 32px;
              border-radius:12px;margin-bottom:28px;">
    <h1 style="color:#fff;margin:0;font-size:22px;letter-spacing:-0.3px;">
      🔥 YouTube Comment Digest
    </h1>
    <p style="color:rgba(255,255,255,.88);margin:6px 0 0;font-size:14px;">
      {date_str} &bull; Last {days_back} days &bull; {total_comments:,} comments analysed
    </p>
  </div>

  <div style="background:#fff8f0;border:1px solid #ffcc80;padding:20px 24px;
              border-radius:8px;margin-bottom:32px;">
    <h2 style="margin:0 0 10px;color:#bf360c;font-size:16px;">Executive Summary</h2>
    <div style="color:#444;font-size:14px;line-height:1.75;">{summary_html}</div>
  </div>

  <h2 style="font-size:16px;color:#222;border-bottom:2px solid #ff4500;
             padding-bottom:8px;margin-bottom:20px;">Per-Video Breakdown</h2>
  {video_cards}

  <p style="margin-top:40px;font-size:11px;color:#aaa;border-top:1px solid #eee;
            padding-top:16px;">
    Generated by YouTube Comment Digest &bull; Powered by Claude AI
  </p>
</body>
</html>"""

    plain = (
        f"YouTube Comment Digest — {date_str}\n"
        f"Last {days_back} days | {total_comments:,} comments\n\n"
        f"SUMMARY\n{summary}\n\n"
        + "\n\n".join(f"--- {t} ---\n{a}" for t, a in analyses)
    )
    return subject, html, plain


def send_email(subject: str, html: str, plain: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        srv.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Comment Digest")
    parser.add_argument("--days",    type=int, default=DAYS_BACK,  help="Days to look back")
    parser.add_argument("--channel", type=str, default=CHANNEL_ID, help="YouTube channel ID")
    args = parser.parse_args()

    channel_id = args.channel
    days_back  = args.days

    if not channel_id:
        sys.exit("Error: YOUTUBE_CHANNEL_ID not set. Pass --channel or set it in .env")
    if not ANTHROPIC_API_KEY:
        sys.exit("Error: ANTHROPIC_API_KEY not set in .env")
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        sys.exit("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env")
    if not TO_EMAIL:
        sys.exit("Error: TO_EMAIL not set in .env")

    try:
        from googleapiclient.discovery import build
        import anthropic
    except ImportError:
        sys.exit("Dependencies missing. Run: pip install -r requirements.txt")

    print(f"[1/5] Building YouTube client …")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"[2/5] Fetching videos from the last {days_back} day(s) …")
    videos = fetch_recent_videos(youtube, channel_id, days_back)
    print(f"      Found {len(videos)} video(s).")

    if not videos:
        print("No recent videos — nothing to send. Exiting.")
        return

    print("[3/5] Fetching comments and analysing with Claude …")
    analyses, total_comments = [], 0
    for v in videos:
        print(f"  → {v['title']}")
        comments = fetch_comments(youtube, v["id"], MAX_COMMENTS)
        total_comments += len(comments)
        print(f"     {len(comments)} comments fetched …")
        result = analyze_video(client, v["title"], comments)
        if result:
            analyses.append((v["title"], result))

    if not analyses:
        print("No analysable comments found. Exiting.")
        return

    print("[4/5] Generating executive summary …")
    summary = overall_summary(client, analyses)

    print("[5/5] Building and sending email …")
    subject, html, plain = build_email(analyses, summary, days_back, total_comments)
    send_email(subject, html, plain)
    print(f"Done! Digest sent to {TO_EMAIL}")


if __name__ == "__main__":
    main()
