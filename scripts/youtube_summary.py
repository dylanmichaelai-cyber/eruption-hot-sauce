#!/usr/bin/env python3
"""
YouTube Comment Summary Routine
Fetches recent comments from your YouTube channel, analyzes sentiment
with Claude, and emails you a structured improvement report.

Usage:
  python3 scripts/youtube_summary.py

Configuration:
  Copy .env.example to .env and fill in your values, then:
  export $(grep -v '^#' .env | xargs) && python3 scripts/youtube_summary.py

Cron (run every Monday at 8am):
  0 8 * * 1 cd /path/to/repo && export $(grep -v '^#' .env | xargs) && python3 scripts/youtube_summary.py >> logs/youtube_summary.log 2>&1
"""

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from googleapiclient.discovery import build
import anthropic

YOUTUBE_API_KEY         = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID      = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY       = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_ADDRESS           = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_APP_PASSWORD      = os.environ.get("EMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL         = os.environ.get("RECIPIENT_EMAIL", EMAIL_ADDRESS)
MAX_VIDEOS              = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO  = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))


def get_recent_videos(youtube, channel_id, max_videos):
    channel_resp = youtube.channels().list(
        part="contentDetails,snippet",
        id=channel_id,
    ).execute()

    if not channel_resp.get("items"):
        raise ValueError(f"Channel '{channel_id}' not found. Check your YOUTUBE_CHANNEL_ID.")

    channel       = channel_resp["items"][0]
    channel_title = channel["snippet"]["title"]
    uploads_id    = channel["contentDetails"]["relatedPlaylists"]["uploads"]

    playlist_resp = youtube.playlistItems().list(
        part="snippet",
        playlistId=uploads_id,
        maxResults=max_videos,
    ).execute()

    videos = []
    for item in playlist_resp.get("items", []):
        s = item["snippet"]
        videos.append({
            "id":           s["resourceId"]["videoId"],
            "title":        s["title"],
            "published_at": s["publishedAt"],
        })

    return channel_title, videos


def get_video_comments(youtube, video_id, max_comments):
    comments = []
    try:
        resp = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_comments, 100),
            order="relevance",
        ).execute()

        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text":   top["textDisplay"],
                "likes":  top["likeCount"],
                "author": top["authorDisplayName"],
            })
    except Exception as e:
        print(f"  Warning: could not fetch comments for {video_id}: {e}")

    return comments


def analyze_with_claude(channel_title, video_data):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build comment dump — cap at 30 comments per video to stay within context
    dump = f"YouTube Channel: {channel_title}\n\n"
    for v in video_data:
        dump += f"=== {v['title']} ===\n"
        if v["comments"]:
            for c in v["comments"][:30]:
                dump += f"[{c['likes']} likes] {c['text']}\n"
        else:
            dump += "(no comments or comments disabled)\n"
        dump += "\n"

    prompt = f"""\
You are a content-strategy analyst reviewing YouTube comments for a creator.
Here is a recent snapshot of their channel comments:

{dump}

Write a clear, actionable report with exactly these sections:

## Overall Sentiment
State the approximate positive/neutral/negative split and describe the general mood in 2–3 sentences.

## What Viewers Love
3–5 bullet points of recurring praise — be specific, not generic.

## Common Concerns & Criticism
3–5 bullet points of recurring complaints. Be honest and constructive.

## Actionable Improvements
5 concrete, specific things the creator can do differently based on this feedback. Number them.

## Comments Worth Your Attention
Quote 2–3 individual comments (with any context needed) that the creator should personally read.

## Executive Summary
2–3 sentences the creator can read in 10 seconds to get the gist.

Tone: honest, encouraging, professional."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def md_to_html(text):
    """Minimal Markdown → HTML: headings, bold, bullets, numbered lists."""
    html = []
    in_ul = False
    in_ol = False

    for line in text.split("\n"):
        # H2
        if line.startswith("## "):
            if in_ul: html.append("</ul>"); in_ul = False
            if in_ol: html.append("</ol>"); in_ol = False
            html.append(f'<h3 style="color:#b00;margin-top:1.4em">{line[3:]}</h3>')
            continue

        # Unordered bullet
        m = re.match(r'^[-*] (.+)', line.strip())
        if m:
            if in_ol: html.append("</ol>"); in_ol = False
            if not in_ul: html.append("<ul>"); in_ul = True
            html.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Ordered list
        m = re.match(r'^\d+\. (.+)', line.strip())
        if m:
            if in_ul: html.append("</ul>"); in_ul = False
            if not in_ol: html.append("<ol>"); in_ol = True
            html.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Close open lists on blank/paragraph lines
        if in_ul: html.append("</ul>"); in_ul = False
        if in_ol: html.append("</ol>"); in_ol = False

        if line.strip() == "":
            continue

        html.append(f"<p>{_inline(line)}</p>")

    if in_ul: html.append("</ul>")
    if in_ol: html.append("</ol>")

    return "\n".join(html)


def _inline(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'"(.+?)"', r'<em>"\1"</em>', text)
    return text


def build_html_email(channel_title, videos_count, comments_count, analysis_md):
    today = datetime.now().strftime("%B %d, %Y")
    body  = md_to_html(analysis_md)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#222;">
  <div style="background:#b00;color:#fff;padding:16px 20px;border-radius:6px 6px 0 0;">
    <h2 style="margin:0;">YouTube Comment Summary</h2>
    <p style="margin:4px 0 0;opacity:.85;">{channel_title} &mdash; {today}</p>
  </div>
  <div style="background:#f9f9f9;padding:12px 20px;border:1px solid #ddd;border-top:none;">
    <span style="margin-right:20px;">📹 <strong>{videos_count}</strong> videos</span>
    <span>💬 <strong>{comments_count}</strong> comments analyzed</span>
  </div>
  <div style="padding:8px 4px;line-height:1.75;">
    {body}
  </div>
  <hr style="margin-top:32px;border:none;border-top:1px solid #eee;">
  <p style="font-size:11px;color:#aaa;">
    Generated by youtube_summary.py &mdash; eruption-hot-sauce repo
  </p>
</body>
</html>"""


def send_email(subject, html_body):
    msg              = MIMEMultipart("alternative")
    msg["Subject"]   = subject
    msg["From"]      = EMAIL_ADDRESS
    msg["To"]        = RECIPIENT_EMAIL

    plain = re.sub(r'<[^>]+>', '', html_body)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())


def main():
    required = {
        "YOUTUBE_API_KEY":    YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": YOUTUBE_CHANNEL_ID,
        "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
        "EMAIL_ADDRESS":      EMAIL_ADDRESS,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("See .env.example for setup instructions.")
        return 1

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] Starting YouTube comment summary routine...")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {YOUTUBE_CHANNEL_ID}...")
    channel_title, videos = get_recent_videos(youtube, YOUTUBE_CHANNEL_ID, MAX_VIDEOS)
    print(f"Channel: {channel_title} — {len(videos)} video(s) found")

    video_data = []
    for v in videos:
        print(f"  [{v['published_at'][:10]}] {v['title'][:65]}...")
        comments = get_video_comments(youtube, v["id"], MAX_COMMENTS_PER_VIDEO)
        print(f"    {len(comments)} comments fetched")
        video_data.append({**v, "comments": comments})

    total_comments = sum(len(v["comments"]) for v in video_data)
    print(f"\nTotal comments: {total_comments}")

    if total_comments == 0:
        print("No comments found — nothing to summarize.")
        return 0

    print("Analyzing with Claude...")
    analysis = analyze_with_claude(channel_title, video_data)

    today   = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Comment Summary — {channel_title} ({today})"
    html    = build_html_email(channel_title, len(videos), total_comments, analysis)

    print(f"Sending email to {RECIPIENT_EMAIL}...")
    send_email(subject, html)
    print("Done — email sent successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
