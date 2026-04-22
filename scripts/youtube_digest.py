#!/usr/bin/env python3
"""
YouTube Comment Digest
======================
Fetches recent comments from your YouTube channel, uses Claude to analyze
viewer sentiment and improvement areas, then emails you a formatted digest.

Usage:
    python youtube_digest.py

Schedule weekly with cron (every Monday at 9 AM):
    0 9 * * 1 cd /path/to/scripts && python youtube_digest.py >> digest.log 2>&1
"""

import os
import sys
import smtplib
import html
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.environ.get("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_SENDER       = os.environ.get("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENT    = os.environ.get("EMAIL_RECIPIENT", GMAIL_SENDER)
CHANNEL_ID         = os.environ.get("YOUTUBE_CHANNEL_ID", "")

MAX_VIDEOS             = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))
LOOKBACK_DAYS          = int(os.environ.get("LOOKBACK_DAYS", "7"))


# ── YouTube helpers ────────────────────────────────────────────────────────

def get_youtube_client():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def get_uploads_playlist_id(yt, channel_id: str) -> str:
    """Return the 'uploads' playlist ID for a channel."""
    resp = yt.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError(f"Channel '{channel_id}' not found. Check YOUTUBE_CHANNEL_ID.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_recent_video_ids(yt, uploads_playlist_id: str, max_videos: int, since: datetime) -> list[dict]:
    """Return up to max_videos video IDs/titles published after `since`."""
    videos = []
    page_token = None

    while len(videos) < max_videos:
        resp = yt.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=min(50, max_videos - len(videos)),
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet = item["snippet"]
            published = datetime.fromisoformat(
                snippet["publishedAt"].replace("Z", "+00:00")
            )
            if published >= since:
                videos.append({
                    "id": snippet["resourceId"]["videoId"],
                    "title": snippet["title"],
                    "published": published.strftime("%Y-%m-%d"),
                })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return videos[:max_videos]


def get_comments_for_video(yt, video_id: str, max_comments: int) -> list[str]:
    """Return top-level comment texts for a video."""
    comments = []
    page_token = None

    while len(comments) < max_comments:
        try:
            resp = yt.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_comments - len(comments)),
                order="relevance",
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            if e.resp.status == 403:
                # Comments disabled on this video
                return comments
            raise

        for thread in resp.get("items", []):
            text = thread["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(text)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return comments[:max_comments]


def fetch_all_comments(yt, channel_id: str) -> list[dict]:
    """Fetch comments across recent videos and return structured data."""
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    print(f"Fetching uploads playlist for channel {channel_id}…")
    playlist_id = get_uploads_playlist_id(yt, channel_id)

    print(f"Fetching up to {MAX_VIDEOS} videos since {since.date()}…")
    videos = get_recent_video_ids(yt, playlist_id, MAX_VIDEOS, since)
    print(f"Found {len(videos)} video(s).")

    results = []
    for video in videos:
        print(f"  Fetching comments for: {video['title'][:60]}…")
        comments = get_comments_for_video(yt, video["id"], MAX_COMMENTS_PER_VIDEO)
        results.append({**video, "comments": comments})
        print(f"    → {len(comments)} comment(s) collected.")

    return results


# ── Claude analysis ────────────────────────────────────────────────────────

def build_prompt(videos: list[dict]) -> str:
    parts = []
    total_comments = 0

    for v in videos:
        if not v["comments"]:
            continue
        parts.append(f"### {v['title']} (published {v['published']})")
        for i, c in enumerate(v["comments"], 1):
            parts.append(f"{i}. {c}")
        total_comments += len(v["comments"])
        parts.append("")

    if not parts:
        return ""

    body = "\n".join(parts)
    return f"""Below are {total_comments} YouTube comments across {len(videos)} recent video(s) on my channel.

{body}

---

Please analyze these comments and write a detailed digest with the following sections:

## 1. Overall Sentiment
A short paragraph describing the general mood and tone of the audience.

## 2. What Viewers Love
Bullet-point list of specific things viewers are praising or responding positively to.

## 3. Concerns & Criticism
Bullet-point list of recurring complaints, confusion points, or negative feedback.

## 4. Suggested Improvements
Concrete, actionable recommendations I can implement in future videos based on the feedback.

## 5. Notable Comments
A few standout comments worth highlighting (positive or constructive).

Be specific and reference actual comments where helpful. Write in a direct, friendly tone as if giving advice to a creator you want to succeed."""


def analyze_with_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print("Sending comments to Claude for analysis…")
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    return next(
        (block.text for block in response.content if block.type == "text"),
        "No analysis generated.",
    )


# ── Email formatting ───────────────────────────────────────────────────────

def markdown_to_html(text: str) -> str:
    """Convert the simple Markdown Claude returns into clean HTML."""
    lines = text.split("\n")
    html_lines = []
    in_list = False

    for line in lines:
        if line.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- ") or line.startswith("• "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip() == "":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{html.escape(line)}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def build_email_html(analysis: str, video_count: int, comment_count: int) -> str:
    date_str = datetime.now().strftime("%B %d, %Y")
    analysis_html = markdown_to_html(analysis)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Georgia, serif; max-width: 700px; margin: 0 auto; padding: 24px; color: #222; }}
  h1 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 8px; }}
  h2 {{ color: #c0392b; margin-top: 28px; }}
  p  {{ line-height: 1.7; }}
  ul {{ line-height: 1.8; }}
  li {{ margin-bottom: 4px; }}
  .meta {{ background: #f8f4f0; border-left: 4px solid #c0392b;
            padding: 12px 16px; margin-bottom: 24px; font-size: 14px; }}
  .footer {{ margin-top: 40px; font-size: 12px; color: #888; border-top: 1px solid #ddd; padding-top: 12px; }}
</style>
</head>
<body>
  <h1>🌋 YouTube Comment Digest</h1>
  <div class="meta">
    <strong>Period:</strong> Last {LOOKBACK_DAYS} days &nbsp;|&nbsp;
    <strong>Videos analysed:</strong> {video_count} &nbsp;|&nbsp;
    <strong>Comments analysed:</strong> {comment_count} &nbsp;|&nbsp;
    <strong>Generated:</strong> {date_str}
  </div>

  {analysis_html}

  <div class="footer">
    Digest generated by Claude (claude-opus-4-7) · Eruption Hot Sauce YouTube Analytics
  </div>
</body>
</html>"""


# ── Email sending ──────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT

    msg.attach(MIMEText(html_body, "html"))

    print(f"Sending email to {EMAIL_RECIPIENT}…")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    print("Email sent successfully.")


# ── Main ───────────────────────────────────────────────────────────────────

def validate_env() -> None:
    missing = [
        name for name, val in {
            "YOUTUBE_API_KEY":    YOUTUBE_API_KEY,
            "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
            "GMAIL_SENDER":       GMAIL_SENDER,
            "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
            "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        }.items()
        if not val
    ]
    if missing:
        print("ERROR: Missing required environment variables:")
        for name in missing:
            print(f"  • {name}")
        print("\nCopy .env.example to .env and fill in the values.")
        sys.exit(1)


def main() -> None:
    validate_env()

    yt = get_youtube_client()
    videos = fetch_all_comments(yt, CHANNEL_ID)

    total_comments = sum(len(v["comments"]) for v in videos)
    if total_comments == 0:
        print("No comments found for the selected period. Nothing to send.")
        return

    print(f"\nTotal comments collected: {total_comments} across {len(videos)} video(s).")

    prompt = build_prompt(videos)
    analysis = analyze_with_claude(prompt)

    subject = (
        f"YouTube Comment Digest — {datetime.now().strftime('%b %d, %Y')} "
        f"({total_comments} comments)"
    )
    email_html = build_email_html(analysis, len(videos), total_comments)
    send_email(subject, email_html)

    print("\nDone! ✓")


if __name__ == "__main__":
    main()
