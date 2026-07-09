#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel, analyzes viewer sentiment
and improvement areas using Claude, then sends a summary email via SMTP.

Required environment variables:
  YOUTUBE_API_KEY      - YouTube Data API v3 key (no domain restrictions)
  YOUTUBE_CHANNEL_ID   - Your channel ID (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)
                         Find it: YouTube Studio → Settings → Channel → Basic Info
  ANTHROPIC_API_KEY    - Anthropic API key for Claude analysis
  SMTP_USER            - Gmail address to send from (e.g. you@gmail.com)
  SMTP_PASS            - Gmail App Password (myaccount.google.com/apppasswords)
  EMAIL_TO             - Address to receive the digest (default: same as SMTP_USER)
  DAYS_BACK            - How many days of videos to analyze (default: 7)
"""

import os
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import requests
import anthropic

# ── Configuration ────────────────────────────────────────────────────────────

YOUTUBE_API_KEY    = os.environ["YOUTUBE_API_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
SMTP_USER          = os.environ["SMTP_USER"]
SMTP_PASS          = os.environ["SMTP_PASS"]
EMAIL_TO           = os.environ.get("EMAIL_TO", SMTP_USER)
DAYS_BACK          = int(os.environ.get("DAYS_BACK", "7"))

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS   = 15
MAX_COMMENTS = 50   # per video

# ── YouTube API ───────────────────────────────────────────────────────────────

def yt_get(endpoint, **params):
    params["key"] = YOUTUBE_API_KEY
    resp = requests.get(f"{YOUTUBE_BASE}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_recent_videos():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    data = yt_get(
        "search",
        channelId=YOUTUBE_CHANNEL_ID,
        part="snippet",
        type="video",
        publishedAfter=cutoff,
        maxResults=MAX_VIDEOS,
        order="date",
    )
    return [
        {
            "id":        item["id"]["videoId"],
            "title":     item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
            "url":       f"https://youtube.com/watch?v={item['id']['videoId']}",
        }
        for item in data.get("items", [])
    ]


def get_video_stats(video_ids):
    """Fetch like/view counts in one batch call."""
    data = yt_get("videos", id=",".join(video_ids), part="statistics")
    return {
        item["id"]: item.get("statistics", {})
        for item in data.get("items", [])
    }


def get_comments(video_id):
    try:
        data = yt_get(
            "commentThreads",
            videoId=video_id,
            part="snippet",
            maxResults=MAX_COMMENTS,
            order="relevance",
            textFormat="plainText",
        )
    except requests.HTTPError as exc:
        if exc.response.status_code in (403, 400):
            return []   # comments disabled or restricted
        raise
    return [
        {
            "author":    c["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
            "text":      c["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
            "likes":     c["snippet"]["topLevelComment"]["snippet"]["likeCount"],
            "published": c["snippet"]["topLevelComment"]["snippet"]["publishedAt"],
        }
        for c in data.get("items", [])
    ]


# ── Analysis ──────────────────────────────────────────────────────────────────

def build_comment_block(videos_with_comments):
    lines = []
    for v in videos_with_comments:
        lines.append(f"\n### {v['title']} ({v['url']})")
        if not v["comments"]:
            lines.append("  (no comments)")
            continue
        for c in v["comments"][:30]:
            prefix = f"  [{c['likes']}♥] {c['author']}: "
            lines.append(prefix + c["text"])
    return "\n".join(lines)


def analyze_with_claude(videos_with_comments):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    comment_block = build_comment_block(videos_with_comments)
    total = sum(len(v["comments"]) for v in videos_with_comments)

    prompt = f"""You are analyzing {total} YouTube comments across {len(videos_with_comments)} videos for a content creator. Provide a concise, actionable digest with these sections:

**1. Overall Sentiment** (1-2 sentences — positive / mixed / negative and why)

**2. What Viewers Love** (bullet list of specific praised elements)

**3. Common Complaints & Concerns** (bullet list — be honest, don't sugarcoat)

**4. Frequently Requested Improvements** (bullet list of viewer asks)

**5. Top 5 Actionable Recommendations** (numbered list — specific, implementable things to improve the next video)

**6. Standout Comments** (2-3 quotes worth reading — copy them verbatim with author name)

Keep each section tight. Skip any section if there is genuinely nothing to report.

---
{comment_block}
"""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def build_html(analysis_md, videos_with_comments, week_label):
    import re

    # Convert basic Markdown to HTML
    html_body = analysis_md
    html_body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_body)
    html_body = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html_body)
    html_body = re.sub(r"^#{1,3} (.+)$", r"<h3>\1</h3>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^---$", "<hr>", html_body, flags=re.MULTILINE)
    html_body = html_body.replace("\n", "<br>\n")

    video_rows = "".join(
        f"<tr><td><a href='{v['url']}'>{v['title']}</a></td>"
        f"<td style='text-align:center'>{len(v['comments'])}</td></tr>"
        for v in videos_with_comments
    )

    total_comments = sum(len(v["comments"]) for v in videos_with_comments)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#222">
  <div style="background:#FF4500;padding:20px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;color:#fff;font-size:24px">🔥 YouTube Comment Digest</h1>
    <p style="margin:4px 0 0;color:#ffd0b0;font-size:14px">Week of {week_label} &nbsp;·&nbsp; {len(videos_with_comments)} videos &nbsp;·&nbsp; {total_comments} comments</p>
  </div>

  <div style="background:#fff8f6;padding:16px;border:1px solid #f0d0c0;border-top:none;border-radius:0 0 8px 8px">

    <h2 style="color:#CC3300;margin-top:8px">Videos Analyzed</h2>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead><tr style="background:#f0d0c0">
        <th style="text-align:left;padding:6px">Video</th>
        <th style="padding:6px">Comments</th>
      </tr></thead>
      <tbody>{video_rows}</tbody>
    </table>

    <h2 style="color:#CC3300;margin-top:20px">Analysis</h2>
    <div style="background:#fff;padding:14px;border-radius:6px;border:1px solid #e8cfc0;font-size:15px;line-height:1.6">
      {html_body}
    </div>

    <p style="color:#aaa;font-size:11px;margin-top:20px;text-align:center">
      Generated by the YouTube Comment Digest routine &nbsp;·&nbsp; {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    </p>
  </div>
</body>
</html>"""


def send_email(subject, html_body, text_body):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as srv:
        srv.starttls()
        srv.login(SMTP_USER, SMTP_PASS)
        srv.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())

    print(f"✓ Email sent → {EMAIL_TO}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Fetching videos for channel {YOUTUBE_CHANNEL_ID} …")
    videos = get_recent_videos()
    if not videos:
        print("No videos found in the past", DAYS_BACK, "days. Nothing to report.")
        return

    print(f"Found {len(videos)} video(s). Fetching comments …")
    videos_with_comments = []
    for v in videos:
        comments = get_comments(v["id"])
        videos_with_comments.append({**v, "comments": comments})
        print(f"  {v['title'][:55]:<55} {len(comments):>3} comments")

    total_comments = sum(len(v["comments"]) for v in videos_with_comments)
    if total_comments == 0:
        print("No comments found. Sending a note anyway …")

    print("Analyzing with Claude …")
    analysis = analyze_with_claude(videos_with_comments)

    week_label = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d, %Y")
    subject = f"🔥 YouTube Comment Digest — Week of {week_label}"

    html_body = build_html(analysis, videos_with_comments, week_label)
    text_body = f"YouTube Comment Digest — Week of {week_label}\n\n{analysis}"

    print("Sending email …")
    send_email(subject, html_body, text_body)
    print("Done.")


if __name__ == "__main__":
    main()
