#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches comments from your YouTube channel, analyzes sentiment and feedback
using Claude AI, and emails you a summary report.

Setup:
  1. Set environment variables (or edit the CONFIG section below):
       YOUTUBE_API_KEY   - YouTube Data API v3 key
       YOUTUBE_CHANNEL_ID - Your YouTube channel ID (e.g. UCxxxxxx)
       ANTHROPIC_API_KEY  - Anthropic API key for Claude
       GMAIL_ADDRESS      - Your Gmail address (sender)
       GMAIL_APP_PASSWORD - Gmail App Password (not your login password)
                            Generate at: myaccount.google.com/apppasswords
       RECIPIENT_EMAIL    - Email address to send the report to

  2. Run:  python3 youtube_comment_summary.py

  3. Schedule with cron (e.g. weekly on Mondays at 9am):
       0 9 * * 1 cd /path/to/eruption-hot-sauce && python3 youtube_comment_summary.py
"""

import os
import sys
import smtplib
import textwrap
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import anthropic

# ── CONFIG ──────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY",    "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")   # e.g. "UCxxxxxxxxxxxxxxxxxxxxxx"
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS",      "d.mcderm80@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL    = os.getenv("RECIPIENT_EMAIL",    "d.mcderm80@gmail.com")

# How many recent videos to check and how many comments per video
MAX_VIDEOS        = 10
MAX_COMMENTS_PER_VIDEO = 50
# Only fetch comments newer than this many days (0 = all time)
LOOKBACK_DAYS     = 30
# ────────────────────────────────────────────────────────────────────────────

YT_BASE = "https://www.googleapis.com/youtube/v3"


def yt_get(endpoint: str, **params) -> dict:
    params["key"] = YOUTUBE_API_KEY
    resp = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_channel_id_from_handle(handle: str) -> str:
    """Resolve a @handle or custom URL to a channel ID."""
    data = yt_get("search", part="snippet", q=handle, type="channel", maxResults=1)
    items = data.get("items", [])
    if not items:
        raise ValueError(f"No channel found for handle: {handle}")
    return items[0]["snippet"]["channelId"]


def fetch_recent_video_ids(channel_id: str) -> list[dict]:
    """Return list of {id, title} for the channel's most recent videos."""
    videos = []
    page_token = None
    while len(videos) < MAX_VIDEOS:
        params = dict(
            part="snippet",
            channelId=channel_id,
            order="date",
            type="video",
            maxResults=min(50, MAX_VIDEOS - len(videos)),
        )
        if page_token:
            params["pageToken"] = page_token
        data = yt_get("search", **params)
        for item in data.get("items", []):
            vid_id = item["id"].get("videoId")
            if vid_id:
                videos.append({
                    "id":    vid_id,
                    "title": item["snippet"]["title"],
                    "published": item["snippet"]["publishedAt"],
                })
        page_token = data.get("nextPageToken")
        if not page_token or len(videos) >= MAX_VIDEOS:
            break
    return videos[:MAX_VIDEOS]


def fetch_comments(video_id: str) -> list[dict]:
    """Return top-level comments for a video."""
    comments = []
    cutoff = None
    if LOOKBACK_DAYS:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    page_token = None
    try:
        while len(comments) < MAX_COMMENTS_PER_VIDEO:
            params = dict(
                part="snippet",
                videoId=video_id,
                order="relevance",
                maxResults=min(100, MAX_COMMENTS_PER_VIDEO - len(comments)),
            )
            if page_token:
                params["pageToken"] = page_token
            data = yt_get("commentThreads", **params)
            for item in data.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                published = top["publishedAt"]
                if cutoff:
                    pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if pub_dt < cutoff:
                        continue
                comments.append({
                    "text":      top["textDisplay"],
                    "likes":     top["likeCount"],
                    "published": published,
                    "author":    top["authorDisplayName"],
                })
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    except requests.HTTPError as e:
        # Comments disabled on this video
        if e.response.status_code == 403:
            pass
        else:
            raise
    return comments


def analyze_with_claude(videos_with_comments: list[dict]) -> str:
    """Send all comments to Claude and get a structured analysis."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build a condensed text block so we don't blow the context limit
    lines = []
    total_comments = 0
    for v in videos_with_comments:
        if not v["comments"]:
            continue
        lines.append(f'\n## Video: "{v["title"]}"')
        for c in v["comments"]:
            snippet = c["text"][:300].replace("\n", " ")
            lines.append(f'  - [👍{c["likes"]}] {snippet}')
            total_comments += 1

    if not lines:
        return "No comments were found in the specified time window."

    comment_block = "\n".join(lines)

    prompt = f"""You are analyzing YouTube comments for a hot sauce brand called **Eruption Hot Sauce**.

Below are comments from the channel's {len(videos_with_comments)} most recent videos (past {LOOKBACK_DAYS or 'all'} days, {total_comments} comments total).

{comment_block}

Please write a concise, friendly summary report with the following sections:

1. **Overall Sentiment** – One paragraph describing how viewers generally feel (positive, mixed, negative) and the dominant mood.

2. **What People Love** – Bullet list of specific things viewers praise most (flavors, presentation, content style, personality, etc.).

3. **Common Complaints or Concerns** – Bullet list of recurring criticisms or requests, even minor ones.

4. **Actionable Improvements** – Concrete, prioritized suggestions based on the feedback (e.g. "Viewers frequently ask for milder options – consider a beginner-friendly tier").

5. **Standout Comments** – 2–3 verbatim comments worth reading (positive, constructive, or insightful).

Keep the tone encouraging and the language plain. Aim for a report a busy creator can read in under 2 minutes."""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_email(subject: str, body_text: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())


def markdown_to_html(md: str) -> str:
    """Minimal Markdown→HTML for the email body."""
    import re
    lines = md.split("\n")
    html_lines = []
    in_ul = False
    for line in lines:
        if line.startswith("## "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("**") and line.endswith("**"):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h3>{line[2:-2]}</h3>")
        elif re.match(r"^\d+\.\s+\*\*", line):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            # "1. **Title** – rest"
            line = re.sub(r"^(\d+)\.\s+\*\*(.+?)\*\*", r"<strong>\2</strong>", line)
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            html_lines.append(f"<p>{line}</p>")
        elif line.startswith("- "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            inner = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line[2:])
            html_lines.append(f"<li>{inner}</li>")
        else:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if line.strip():
                inner = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
                html_lines.append(f"<p>{inner}</p>")
    if in_ul:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def build_html_email(analysis: str, videos: list[dict], total_comments: int) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    body  = markdown_to_html(analysis)
    video_rows = "".join(
        f'<tr><td style="padding:4px 8px;">{v["title"]}</td>'
        f'<td style="padding:4px 8px;text-align:center;">{len(v["comments"])}</td></tr>'
        for v in videos
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; color: #222; max-width: 680px; margin: auto; padding: 24px; }}
  h1   {{ color: #c0392b; }}
  h2   {{ color: #c0392b; border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  h3   {{ color: #333; }}
  ul   {{ padding-left: 20px; }}
  li   {{ margin-bottom: 6px; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
  th,td {{ border: 1px solid #ddd; font-size: 14px; }}
  th   {{ background: #f9f9f9; padding: 6px 8px; }}
  .footer {{ font-size: 12px; color: #999; margin-top: 32px; }}
</style>
</head>
<body>
<h1>🌋 Eruption Hot Sauce – YouTube Comment Report</h1>
<p><em>Generated {today} &nbsp;|&nbsp; {total_comments} comments analyzed across {len(videos)} videos
{f"(last {LOOKBACK_DAYS} days)" if LOOKBACK_DAYS else ""}</em></p>

<h2>Videos Analyzed</h2>
<table>
  <tr><th>Video</th><th>Comments</th></tr>
  {video_rows}
</table>

{body}

<div class="footer">
  This report was automatically generated by your YouTube Comment Summary routine.<br>
  To adjust frequency or settings, edit <code>youtube_comment_summary.py</code>.
</div>
</body>
</html>"""


def validate_config() -> list[str]:
    errors = []
    if not YOUTUBE_API_KEY:
        errors.append("YOUTUBE_API_KEY is not set")
    if not YOUTUBE_CHANNEL_ID:
        errors.append("YOUTUBE_CHANNEL_ID is not set (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)")
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set")
    if not GMAIL_APP_PASSWORD:
        errors.append("GMAIL_APP_PASSWORD is not set (generate at myaccount.google.com/apppasswords)")
    return errors


def main():
    print("🌋 Eruption Hot Sauce – YouTube Comment Summary")
    print("=" * 50)

    errors = validate_config()
    if errors:
        print("\n⚠️  Missing configuration:")
        for e in errors:
            print(f"   • {e}")
        print("\nSet the above as environment variables or edit the CONFIG section in this file.")
        sys.exit(1)

    channel_id = YOUTUBE_CHANNEL_ID
    # Support @handle format
    if channel_id.startswith("@"):
        print(f"Resolving handle {channel_id}...")
        channel_id = get_channel_id_from_handle(channel_id)
        print(f"  → Channel ID: {channel_id}")

    print(f"\nFetching up to {MAX_VIDEOS} recent videos...")
    videos = fetch_recent_video_ids(channel_id)
    print(f"  Found {len(videos)} video(s)")

    total_comments = 0
    for v in videos:
        print(f"  Fetching comments for: {v['title'][:60]}...")
        v["comments"] = fetch_comments(v["id"])
        total_comments += len(v["comments"])
        print(f"    → {len(v['comments'])} comment(s)")

    print(f"\nAnalyzing {total_comments} comments with Claude...")
    analysis = analyze_with_claude(videos)

    subject  = f"🌋 YouTube Comment Summary – {datetime.now().strftime('%B %Y')}"
    html     = build_html_email(analysis, videos, total_comments)
    plain    = f"YouTube Comment Summary\n\n{analysis}"

    print(f"\nSending report to {RECIPIENT_EMAIL}...")
    send_email(subject, plain, html)
    print("✅ Done! Check your inbox.")


if __name__ == "__main__":
    main()
