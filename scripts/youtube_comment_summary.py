#!/usr/bin/env python3
"""
YouTube Comment Summary Routine for Eruption Hot Sauce
-------------------------------------------------------
Fetches recent comments from your YouTube channel videos,
analyzes them with Claude AI for sentiment and improvement areas,
and emails you a formatted summary report.

Setup: see .env.example for required environment variables.
Schedule with cron: 0 9 * * 1  python3 scripts/youtube_comment_summary.py
"""

import os
import sys
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import anthropic
except ImportError:
    print("Missing dependencies. Run: pip install -r scripts/requirements.txt")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY     = os.environ["YOUTUBE_API_KEY"]
ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER          = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD  = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL     = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)
CHANNEL_ID          = os.environ["YOUTUBE_CHANNEL_ID"]

MAX_VIDEOS              = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO  = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "75"))


# ── YouTube helpers ────────────────────────────────────────────────────────────

def fetch_recent_videos(youtube, channel_id: str, max_results: int) -> list[dict]:
    """Return a list of {id, title, url} for the channel's most recent videos."""
    resp = youtube.search().list(
        channelId=channel_id,
        part="id,snippet",
        order="date",
        type="video",
        maxResults=max_results,
    ).execute()

    videos = []
    for item in resp.get("items", []):
        video_id = item["id"]["videoId"]
        videos.append({
            "id":    video_id,
            "title": item["snippet"]["title"],
            "url":   f"https://youtu.be/{video_id}",
        })
    return videos


def fetch_comments(youtube, video_id: str, max_results: int) -> list[str]:
    """Return top-level comment texts for a video, up to max_results."""
    comments = []
    page_token = None

    while len(comments) < max_results:
        try:
            resp = youtube.commentThreads().list(
                videoId=video_id,
                part="snippet",
                maxResults=min(100, max_results - len(comments)),
                pageToken=page_token,
                textFormat="plainText",
                order="relevance",
            ).execute()
        except HttpError as e:
            # Comments may be disabled on some videos
            if e.resp.status == 403:
                break
            raise

        for item in resp.get("items", []):
            text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(text.strip())

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return comments


# ── Claude analysis ────────────────────────────────────────────────────────────

def build_analysis_prompt(video_data: list[dict]) -> str:
    sections = []
    for v in video_data:
        comment_block = "\n".join(f"- {c}" for c in v["comments"]) or "  (no comments)"
        sections.append(
            f'### "{v["title"]}"\n{v["url"]}\n\n{comment_block}'
        )

    return f"""You are analyzing YouTube comments for Eruption Hot Sauce, a brand known for single-origin volcanic hot sauce with extreme heat.

Below are comments grouped by video. Please provide a structured report with these sections:

1. **Overall Sentiment** — A 2-3 sentence summary of how viewers generally feel across all videos.
2. **What Viewers Love** — Bullet list of specific things people praise most (product, content style, presentation, etc.).
3. **Areas to Improve** — Honest, actionable bullet points based on recurring criticism or confusion.
4. **Frequently Asked Questions / Recurring Topics** — Common themes viewers keep asking about or discussing.
5. **Standout Comments** — 2-3 notable comments (positive or constructively critical) worth reading.
6. **Recommended Next Steps** — 3-5 concrete content or product suggestions based on audience feedback.

Be direct and specific. Skip generic filler advice.

---

{chr(10).join(sections)}
"""


def analyze_with_claude(video_data: list[dict]) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": build_analysis_prompt(video_data)}],
    )
    return message.content[0].text


# ── Email ──────────────────────────────────────────────────────────────────────

def build_email_body(analysis: str, video_data: list[dict], run_date: str) -> str:
    video_lines = "\n".join(
        f'  • {v["title"]} ({len(v["comments"])} comments) — {v["url"]}'
        for v in video_data
    )
    total_comments = sum(len(v["comments"]) for v in video_data)

    return f"""ERUPTION HOT SAUCE — YouTube Comment Report
Generated: {run_date}
Videos analyzed: {len(video_data)} | Total comments: {total_comments}

Videos covered:
{video_lines}

{'─' * 60}

{analysis}

{'─' * 60}
This report was generated automatically by the Eruption comment summary routine.
"""


def send_email(subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    run_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    print(f"[{run_date}] Starting YouTube comment summary…")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"  Fetching up to {MAX_VIDEOS} recent videos from channel {CHANNEL_ID}…")
    videos = fetch_recent_videos(youtube, CHANNEL_ID, MAX_VIDEOS)
    if not videos:
        print("  No videos found. Check your YOUTUBE_CHANNEL_ID.")
        sys.exit(1)

    video_data = []
    for v in videos:
        print(f"  Fetching comments for: {v['title']}")
        comments = fetch_comments(youtube, v["id"], MAX_COMMENTS_PER_VIDEO)
        video_data.append({**v, "comments": comments})
        print(f"    → {len(comments)} comment(s) retrieved")

    print("  Analyzing comments with Claude…")
    analysis = analyze_with_claude(video_data)

    subject = f"Eruption YouTube Report — {datetime.now().strftime('%b %d, %Y')}"
    body    = build_email_body(analysis, video_data, run_date)

    print(f"  Sending report to {RECIPIENT_EMAIL}…")
    send_email(subject, body)

    print("  Done. Report sent successfully.")


if __name__ == "__main__":
    main()
