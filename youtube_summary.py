#!/usr/bin/env python3
"""
YouTube Comment Analyzer
Fetches recent comments from your YouTube channel, analyzes audience sentiment
and improvement suggestions using Claude, then emails you a summary.

Setup:
  pip install anthropic requests

  Required env vars:
    ANTHROPIC_API_KEY   - Your Anthropic API key
    GMAIL_ADDRESS       - Your Gmail address (sender)
    GMAIL_APP_PASSWORD  - Gmail App Password
                          (myaccount.google.com > Security > App passwords)
    YOUTUBE_CHANNEL_ID  - Your channel ID
                          (youtube.com > Your Channel > About, or use the helper below)

  Optional env vars:
    RECIPIENT_EMAIL     - Defaults to GMAIL_ADDRESS
    MAX_VIDEOS          - Recent videos to scan (default: 10)
    MAX_COMMENTS        - Comments per video (default: 100)

Finding your channel ID:
  1. Go to youtube.com and sign in
  2. Click your avatar > "Your channel"
  3. The URL will be youtube.com/channel/UC... — copy the UC... part
  OR: use youtube.com/@handle and run:
    python3 -c "
    import requests, sys
    key = 'AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c'
    handle = sys.argv[1]  # e.g. @YourHandle
    r = requests.get('https://www.googleapis.com/youtube/v3/channels',
        params={'part':'id,snippet','forHandle':handle,'key':key}).json()
    for item in r.get('items', []):
        print(item['id'], item['snippet']['title'])
    " @YourHandle

Scheduling (runs every day at 8 AM):
  crontab -e
  Add: 0 8 * * * cd /path/to/eruption-hot-sauce && python3 youtube_summary.py
"""

import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Config ────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY = os.environ.get(
    "YOUTUBE_API_KEY", "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c"
)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "") or GMAIL_ADDRESS or "d.mcderm80@gmail.com"

MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS", "100"))

YT_BASE = "https://www.googleapis.com/youtube/v3"


# ── YouTube helpers ───────────────────────────────────────────────────────────

def yt_get(endpoint: str, **params) -> dict:
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_channel_title(channel_id: str) -> str:
    data = yt_get("channels", part="snippet", id=channel_id)
    items = data.get("items", [])
    return items[0]["snippet"]["title"] if items else channel_id


def get_recent_videos(channel_id: str, max_results: int = 10) -> list[dict]:
    # Resolve the uploads playlist
    data = yt_get("channels", part="contentDetails", id=channel_id)
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"Channel not found or not accessible: {channel_id}")
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    next_page = None
    while len(videos) < max_results:
        batch = min(max_results - len(videos), 50)
        params = dict(part="snippet", playlistId=uploads_playlist, maxResults=batch)
        if next_page:
            params["pageToken"] = next_page
        resp = yt_get("playlistItems", **params)
        for item in resp.get("items", []):
            sn = item["snippet"]
            videos.append({
                "id": sn["resourceId"]["videoId"],
                "title": sn["title"],
                "published_at": sn.get("publishedAt", "")[:10],
            })
        next_page = resp.get("nextPageToken")
        if not next_page:
            break
    return videos


def get_comments_for_video(video_id: str, max_results: int = 100) -> list[str]:
    comments = []
    next_page = None
    try:
        while len(comments) < max_results:
            batch = min(max_results - len(comments), 100)
            params = dict(
                part="snippet",
                videoId=video_id,
                maxResults=batch,
                textFormat="plainText",
                order="relevance",
            )
            if next_page:
                params["pageToken"] = next_page
            resp = yt_get("commentThreads", **params)
            for item in resp.get("items", []):
                text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                comments.append(text.strip())
            next_page = resp.get("nextPageToken")
            if not next_page:
                break
    except requests.HTTPError as e:
        # 403 = comments disabled on this video
        if e.response is not None and e.response.status_code == 403:
            return []
        raise
    return comments


# ── Claude analysis ───────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are a YouTube content strategist. Below are comments from a creator's recent videos.
Analyze them and write a concise, actionable email-ready report covering:

1. **Overall Sentiment** — What is the general mood of the audience? (positive / mixed / negative, with evidence)
2. **What viewers love** — Specific themes or elements viewers praise most.
3. **Pain points & criticism** — Recurring complaints, confusion, or negative reactions.
4. **Top improvement suggestions** — Concrete, prioritized things the creator can do better.
5. **Emerging requests** — Topics, formats, or features viewers are asking for.

Be direct and specific. Quote or paraphrase real comments where helpful. Aim for 400–600 words.

---
COMMENTS DATA:
{comments_block}
"""


def analyze_with_claude(video_comment_map: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = []
    total = 0
    for video_title, comments in video_comment_map.items():
        lines.append(f"## {video_title}")
        for c in comments:
            lines.append(f"- {c}")
            total += 1
        lines.append("")

    if total == 0:
        return "No comments were found for the analyzed videos. Comments may be disabled or the channel has no recent activity."

    prompt = ANALYSIS_PROMPT.format(comments_block="\n".join(lines))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def md_to_html(text: str) -> str:
    """Minimal markdown → HTML converter for the analysis output."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    paragraphs = text.split("\n\n")
    html_parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        lines = para.split("\n")
        # Detect list block
        if all(l.strip().startswith(("-", "*", "•")) for l in lines if l.strip()):
            items = "".join(
                f"<li>{l.lstrip('-*• ').strip()}</li>" for l in lines if l.strip()
            )
            html_parts.append(f"<ul>{items}</ul>")
        else:
            html_parts.append(f"<p>{'<br>'.join(lines)}</p>")
    return "\n".join(html_parts)


def build_email(channel_title: str, video_summaries: list[dict], analysis: str) -> tuple[str, str]:
    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Comment Summary — {channel_title} ({date_str})"

    video_rows = "".join(
        f"<tr><td style='padding:6px 10px'>{v['title']}</td>"
        f"<td style='padding:6px 10px;text-align:center;color:#666'>{v['published_at']}</td>"
        f"<td style='padding:6px 10px;text-align:center'>{v['comment_count']}</td></tr>"
        for v in video_summaries
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:24px;color:#222">
  <h2 style="color:#c0392b;margin-bottom:4px">🔥 YouTube Comment Report</h2>
  <p style="color:#888;margin-top:0">{channel_title} &mdash; {date_str}</p>

  <h3 style="border-bottom:2px solid #eee;padding-bottom:6px">Videos Analyzed</h3>
  <table style="border-collapse:collapse;width:100%;font-size:14px">
    <thead>
      <tr style="background:#f9f9f9;color:#555">
        <th style="padding:6px 10px;text-align:left;font-weight:600">Title</th>
        <th style="padding:6px 10px;font-weight:600">Published</th>
        <th style="padding:6px 10px;font-weight:600">Comments read</th>
      </tr>
    </thead>
    <tbody>{video_rows}</tbody>
  </table>

  <h3 style="border-bottom:2px solid #eee;padding-bottom:6px;margin-top:28px">Analysis</h3>
  {md_to_html(analysis)}

  <p style="font-size:12px;color:#aaa;margin-top:32px;border-top:1px solid #eee;padding-top:12px">
    Generated by youtube_summary.py — run this script on a cron schedule for regular updates.
  </p>
</body>
</html>"""
    return subject, html


def send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

    print(f"  ✓ Email sent to {RECIPIENT_EMAIL}")


# ── Main ──────────────────────────────────────────────────────────────────────

def validate_config():
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not GMAIL_ADDRESS:
        missing.append("GMAIL_ADDRESS")
    if not GMAIL_APP_PASSWORD:
        missing.append("GMAIL_APP_PASSWORD")
    if not CHANNEL_ID:
        missing.append("YOUTUBE_CHANNEL_ID")
    if missing:
        print("Error: missing required environment variables:")
        for m in missing:
            print(f"  export {m}='...'")
        print("\nSee the docstring at the top of youtube_summary.py for full setup instructions.")
        sys.exit(1)


def main():
    validate_config()

    print(f"Fetching channel info for {CHANNEL_ID}...")
    channel_title = get_channel_title(CHANNEL_ID)
    print(f"Channel: {channel_title}")

    print(f"Fetching up to {MAX_VIDEOS} recent videos...")
    videos = get_recent_videos(CHANNEL_ID, max_results=MAX_VIDEOS)
    print(f"Found {len(videos)} videos.")

    video_comment_map: dict = {}
    video_summaries = []

    for v in videos:
        label = v["title"][:60]
        print(f"  Fetching comments for: {label!r}...")
        comments = get_comments_for_video(v["id"], max_results=MAX_COMMENTS)
        video_comment_map[v["title"]] = comments
        video_summaries.append({**v, "comment_count": len(comments)})
        print(f"    → {len(comments)} comment(s)")

    print("Analyzing with Claude...")
    analysis = analyze_with_claude(video_comment_map)

    print("Sending summary email...")
    subject, html_body = build_email(channel_title, video_summaries, analysis)
    send_email(subject, html_body)

    print("Done!")


if __name__ == "__main__":
    main()
