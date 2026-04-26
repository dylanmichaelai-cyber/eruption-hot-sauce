#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches comments from your YouTube channel's recent videos, uses Claude AI to
analyze sentiment and extract improvement insights, then emails you a report.

Setup: copy .env.example to .env, fill in your values, then run:
    pip install -r requirements.txt
    python youtube_comment_summary.py
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # dotenv optional; env vars can be set directly in the shell

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("Missing dependency: pip install google-api-python-client")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Missing dependency: pip install anthropic")
    sys.exit(1)


# ── Config ─────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY")
CHANNEL_ID        = os.environ.get("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
RECIPIENT_EMAIL   = os.environ.get("RECIPIENT_EMAIL")
GMAIL_USER        = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

MAX_VIDEOS        = int(os.environ.get("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "75"))


def validate_config():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "RECIPIENT_EMAIL": RECIPIENT_EMAIL,
        "GMAIL_USER": GMAIL_USER,
        "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Error: Missing required environment variables:\n  " + "\n  ".join(missing))
        print("\nCopy scripts/.env.example to scripts/.env and fill in the values.")
        sys.exit(1)


# ── YouTube helpers ─────────────────────────────────────────────────────────

def get_recent_videos(youtube, channel_id: str, max_results: int):
    """Return list of {id, title} dicts for the channel's most recent videos."""
    try:
        resp = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=max_results,
            order="date",
            type="video",
        ).execute()
    except HttpError as e:
        print(f"YouTube API error fetching videos: {e}")
        sys.exit(1)

    videos = []
    for item in resp.get("items", []):
        videos.append({
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        })
    return videos


def get_video_comments(youtube, video_id: str, max_comments: int):
    """Return a list of comment dicts for the given video."""
    comments = []
    page_token = None

    while len(comments) < max_comments:
        try:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_comments - len(comments)),
                pageToken=page_token,
                textFormat="plainText",
                order="relevance",
            ).execute()
        except HttpError as e:
            # Comments disabled (403) or other transient error — skip silently
            if e.resp.status in (403, 400):
                return []
            raise

        for item in resp.get("items", []):
            snip = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": snip["textDisplay"],
                "likes": snip["likeCount"],
                "author": snip["authorDisplayName"],
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return comments


# ── Claude analysis ─────────────────────────────────────────────────────────

def build_comment_block(comments_by_video: dict) -> str:
    """Format comments into a structured text block for the prompt."""
    block = ""
    for video, comments in comments_by_video.items():
        block += f"\n\n### {video}\n"
        for c in comments[:50]:
            likes = f" [👍 {c['likes']}]" if c["likes"] > 0 else ""
            block += f"- {c['text']}{likes}\n"
    return block


def analyze_with_claude(comments_by_video: dict, client: anthropic.Anthropic) -> str:
    """Send comments to Claude and get back an HTML analysis."""
    comment_block = build_comment_block(comments_by_video)
    total = sum(len(v) for v in comments_by_video.values())

    prompt = f"""You are analyzing {total} YouTube comments left on recent videos for "ERUPTION" — a single-origin volcanic hot sauce brand.

Here are the comments grouped by video:{comment_block}

Provide a concise, actionable HTML report covering:

1. <strong>Overall Vibe</strong> — one or two sentences on the general sentiment (positive / mixed / negative) and energy in the comments.

2. <strong>What Viewers Love</strong> — 3–5 bullet points on the most praised aspects (product quality, branding, content style, etc.).

3. <strong>Criticism & Suggestions</strong> — 3–5 bullet points summarising the most common complaints or requests, ranked by frequency.

4. <strong>Top 3 Actionable Improvements</strong> — specific, concrete things to do or change based on the feedback.

5. <strong>Standout Comments</strong> — quote 2–3 particularly insightful, funny, or representative comments verbatim (in <blockquote> tags), with a one-sentence note on why each is notable.

Format the entire response as clean HTML (use <h2>, <ul>, <li>, <blockquote>, <strong>, <em>). No markdown. Keep it tight — assume the reader has 2 minutes."""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ── Email ───────────────────────────────────────────────────────────────────

def send_email(html_body: str, video_count: int, comment_count: int):
    subject = f"🔥 ERUPTION YouTube Report — {datetime.now().strftime('%b %d, %Y')}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table width="640" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.12);">

          <!-- Header -->
          <tr>
            <td style="background:#000;padding:28px 32px;text-align:center;">
              <div style="font-size:28px;font-weight:bold;color:#FF4500;letter-spacing:4px;">ERUPTION</div>
              <div style="color:#888;font-size:13px;margin-top:4px;">YouTube Comment Intelligence Report</div>
              <div style="color:#555;font-size:12px;margin-top:2px;">{datetime.now().strftime('%B %d, %Y')} &nbsp;·&nbsp; {video_count} videos &nbsp;·&nbsp; {comment_count} comments</div>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:28px 32px;color:#222;font-size:15px;line-height:1.7;">
              {html_body}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f9f9f9;padding:16px 32px;text-align:center;border-top:1px solid #eee;">
              <span style="color:#aaa;font-size:11px;">
                Auto-generated by your ERUPTION YouTube Comment Routine
              </span>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    print(f"  Connecting to Gmail SMTP...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    validate_config()

    print("=" * 52)
    print("  ERUPTION YouTube Comment Summary Routine")
    print("=" * 52)

    print(f"\n[1/4] Fetching recent videos (channel: {CHANNEL_ID})...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    videos = get_recent_videos(youtube, CHANNEL_ID, MAX_VIDEOS)

    if not videos:
        print("No videos found. Double-check YOUTUBE_CHANNEL_ID.")
        sys.exit(1)

    print(f"      Found {len(videos)} video(s).")

    print(f"\n[2/4] Fetching comments (up to {MAX_COMMENTS_PER_VIDEO} per video)...")
    comments_by_video = {}
    for v in videos:
        print(f"      • {v['title'][:55]}...")
        comments = get_video_comments(youtube, v["id"], MAX_COMMENTS_PER_VIDEO)
        if comments:
            comments_by_video[f"{v['title']} ({v['published']})"] = comments
            print(f"        → {len(comments)} comment(s)")
        else:
            print(f"        → skipped (comments disabled or none)")

    if not comments_by_video:
        print("\nNo comments found on any video. Nothing to report.")
        sys.exit(0)

    total_comments = sum(len(c) for c in comments_by_video.values())
    print(f"      Total: {total_comments} comment(s) across {len(comments_by_video)} video(s).")

    print(f"\n[3/4] Analysing with Claude AI...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    analysis_html = analyze_with_claude(comments_by_video, client)

    print(f"\n[4/4] Sending email to {RECIPIENT_EMAIL}...")
    send_email(analysis_html, len(comments_by_video), total_comments)

    print("\n✓ Done! Email sent successfully.\n")


if __name__ == "__main__":
    main()
