#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches comments from your YouTube channel, analyzes sentiment with Claude,
and emails a summary report to you.

Required environment variables:
  YOUTUBE_API_KEY    - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID - Your YouTube channel ID (e.g. UCxxxx...)
  ANTHROPIC_API_KEY  - Anthropic API key for Claude analysis
  SMTP_USER          - Gmail address to send from
  SMTP_PASSWORD      - Gmail app password (not your account password)
  REPORT_EMAIL       - Email address to send the report to

Usage:
  python3 youtube_comment_summary.py

Schedule with cron (weekly on Mondays at 9am):
  0 9 * * 1 cd /path/to/eruption-hot-sauce && python3 youtube_comment_summary.py
"""

import os
import json
import smtplib
import textwrap
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
REPORT_EMAIL = os.environ.get("REPORT_EMAIL", SMTP_USER)

MAX_VIDEOS = 10       # most recent videos to scan
MAX_COMMENTS_PER_VIDEO = 50  # top-level comments per video


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def yt_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_uploads_playlist_id(channel_id):
    data = yt_get("channels", {"id": channel_id, "part": "contentDetails"})
    items = data.get("items", [])
    if not items:
        raise ValueError(f"Channel not found: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_recent_videos(playlist_id, max_results=MAX_VIDEOS):
    data = yt_get("playlistItems", {
        "playlistId": playlist_id,
        "part": "snippet",
        "maxResults": max_results,
    })
    videos = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        videos.append({
            "video_id": snippet["resourceId"]["videoId"],
            "title": snippet["title"],
            "published_at": snippet["publishedAt"],
        })
    return videos


def get_comments(video_id, max_results=MAX_COMMENTS_PER_VIDEO):
    try:
        data = yt_get("commentThreads", {
            "videoId": video_id,
            "part": "snippet",
            "maxResults": max_results,
            "order": "relevance",
        })
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            # Comments disabled for this video
            return []
        raise
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "author": top["authorDisplayName"],
            "text": top["textDisplay"],
            "likes": top["likeCount"],
            "published_at": top["publishedAt"],
        })
    return comments


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def analyze_comments_with_claude(videos_with_comments):
    """Send all comments to Claude for sentiment analysis and improvement suggestions."""
    # Build a compact summary of all comments
    comment_blocks = []
    total_comments = 0
    for video in videos_with_comments:
        if not video["comments"]:
            continue
        lines = [f"### Video: {video['title']}"]
        for c in video["comments"]:
            text = c["text"].replace("\n", " ").strip()
            lines.append(f"- [{c['likes']} likes] {text}")
            total_comments += 1
        comment_blocks.append("\n".join(lines))

    if not comment_blocks:
        return "No comments found to analyze.", 0

    prompt = textwrap.dedent(f"""
        You are an expert content strategist analyzing YouTube comments for a hot sauce channel called Eruption Hot Sauce.

        Below are the most recent comments from the channel's videos. Please analyze them and provide:

        1. **Overall Sentiment** — A brief paragraph summarizing how viewers generally feel about the content.
        2. **What Viewers Love** — 3–5 bullet points on what's working well.
        3. **Areas for Improvement** — 3–5 concrete, actionable suggestions based on criticism or recurring requests.
        4. **Notable Comments** — 2–3 standout comments (positive or constructive) worth reading.
        5. **Quick Stats** — Estimate the rough sentiment split (% positive / % neutral / % negative).

        Be specific and reference actual themes from the comments.

        ---
        {chr(10).join(comment_blocks)}
    """).strip()

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-opus-4-8",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(
        f"{ANTHROPIC_BASE_URL}/v1/messages",
        headers=headers,
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"], total_comments


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def build_email_html(analysis, videos_with_comments, total_comments, generated_at):
    video_rows = ""
    for v in videos_with_comments:
        count = len(v["comments"])
        video_rows += f"<tr><td style='padding:4px 8px'>{v['title']}</td><td style='padding:4px 8px;text-align:center'>{count}</td></tr>"

    # Convert markdown-style headers/bullets to basic HTML
    analysis_html = analysis \
        .replace("**", "<strong>", 1)  # handled below properly

    # Simple markdown → HTML conversion
    lines = []
    for line in analysis.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            lines.append(f"<li>{stripped[2:]}</li>")
        elif stripped == "":
            lines.append("<br>")
        else:
            lines.append(f"<p>{stripped}</p>")

    import re
    analysis_html = "\n".join(lines)
    analysis_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", analysis_html)
    analysis_html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", analysis_html)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:24px;color:#222">
  <div style="background:#e63f1f;padding:16px 24px;border-radius:8px 8px 0 0">
    <h1 style="color:#fff;margin:0">🔥 Eruption Hot Sauce — YouTube Insights</h1>
    <p style="color:#ffd0c0;margin:4px 0 0">Generated {generated_at}</p>
  </div>
  <div style="border:1px solid #e63f1f;border-top:none;padding:20px;border-radius:0 0 8px 8px">
    <h2 style="color:#e63f1f">Videos Scanned</h2>
    <table style="border-collapse:collapse;width:100%;font-size:14px">
      <thead>
        <tr style="background:#f5f5f5">
          <th style="padding:4px 8px;text-align:left">Title</th>
          <th style="padding:4px 8px">Comments</th>
        </tr>
      </thead>
      <tbody>{video_rows}</tbody>
      <tfoot>
        <tr style="font-weight:bold">
          <td style="padding:4px 8px">Total</td>
          <td style="padding:4px 8px;text-align:center">{total_comments}</td>
        </tr>
      </tfoot>
    </table>
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <h2 style="color:#e63f1f">Analysis</h2>
    {analysis_html}
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="font-size:12px;color:#888">
      This report was generated automatically by the Eruption Hot Sauce YouTube Comment Routine.<br>
      Powered by YouTube Data API + Claude AI.
    </p>
  </div>
</body>
</html>"""


def send_email(subject, html_body, to_addr, from_addr, password):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(from_addr, password)
        server.sendmail(from_addr, to_addr, msg.as_string())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate required config
    missing = [v for v in ["YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID", "ANTHROPIC_API_KEY",
                            "SMTP_USER", "SMTP_PASSWORD"] if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        print(__doc__)
        return 1

    print(f"[1/5] Fetching uploads playlist for channel {CHANNEL_ID}...")
    playlist_id = get_uploads_playlist_id(CHANNEL_ID)

    print(f"[2/5] Fetching up to {MAX_VIDEOS} recent videos...")
    videos = get_recent_videos(playlist_id)
    print(f"      Found {len(videos)} videos.")

    print(f"[3/5] Fetching comments (up to {MAX_COMMENTS_PER_VIDEO} per video)...")
    videos_with_comments = []
    for v in videos:
        comments = get_comments(v["video_id"])
        videos_with_comments.append({**v, "comments": comments})
        print(f"      {v['title'][:60]}: {len(comments)} comments")

    print("[4/5] Analyzing comments with Claude...")
    analysis, total_comments = analyze_comments_with_claude(videos_with_comments)

    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    html_body = build_email_html(analysis, videos_with_comments, total_comments, generated_at)

    print(f"[5/5] Sending report to {REPORT_EMAIL}...")
    send_email(
        subject=f"🔥 YouTube Comment Insights — {generated_at}",
        html_body=html_body,
        to_addr=REPORT_EMAIL,
        from_addr=SMTP_USER,
        password=SMTP_PASSWORD,
    )
    print("Done! Report sent successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
