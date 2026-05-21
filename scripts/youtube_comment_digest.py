#!/usr/bin/env python3
"""
YouTube Comment Digest for Eruption Hot Sauce
Fetches recent video comments, analyzes them with Claude AI,
and emails a formatted report.
"""

import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Config from environment ──────────────────────────────────────────────────
YOUTUBE_API_KEY   = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID        = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_TO          = os.environ.get("EMAIL_TO", "d.mcderm80@gmail.com")
EMAIL_FROM        = os.environ["EMAIL_FROM"]          # your Gmail address
EMAIL_PASSWORD    = os.environ["EMAIL_APP_PASSWORD"]  # Gmail app password

YT_BASE       = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS    = 10
COMMENTS_PER  = 30   # max comments fetched per video


# ── YouTube helpers ───────────────────────────────────────────────────────────

def fetch_recent_videos():
    params = {
        "key": YOUTUBE_API_KEY,
        "channelId": CHANNEL_ID,
        "part": "snippet",
        "order": "date",
        "type": "video",
        "maxResults": MAX_VIDEOS,
    }
    r = requests.get(f"{YT_BASE}/search", params=params, timeout=15)
    r.raise_for_status()
    return [
        (item["id"]["videoId"], item["snippet"]["title"])
        for item in r.json().get("items", [])
    ]


def fetch_comments(video_id):
    params = {
        "key": YOUTUBE_API_KEY,
        "videoId": video_id,
        "part": "snippet",
        "order": "relevance",
        "maxResults": COMMENTS_PER,
        "textFormat": "plainText",
    }
    try:
        r = requests.get(f"{YT_BASE}/commentThreads", params=params, timeout=15)
        r.raise_for_status()
        out = []
        for item in r.json().get("items", []):
            snip = item["snippet"]["topLevelComment"]["snippet"]
            out.append({
                "author": snip.get("authorDisplayName", ""),
                "text":   snip.get("textDisplay", "")[:400],
                "likes":  snip.get("likeCount", 0),
            })
        return out
    except requests.HTTPError:
        return []   # comments disabled or quota hit


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyze(video_comments: dict) -> str:
    lines = []
    for title, comments in video_comments.items():
        lines.append(f"\n### {title}")
        for c in comments:
            lines.append(f'- [{c["likes"]}👍] {c["author"]}: {c["text"]}')

    prompt = f"""You are analyzing YouTube comments for "Eruption Hot Sauce", a hot sauce brand.

Here are comments from recent videos:

{chr(10).join(lines)}

Write a structured digest with these sections:

**1. Overall Sentiment**
Positive / Neutral / Negative breakdown (rough percentages).

**2. What Viewers Love**
Top 3–5 things people consistently praise.

**3. Criticisms & Concerns**
Recurring complaints or issues raised.

**4. Actionable Improvements**
Concrete, prioritized things to change or try based on viewer feedback.

**5. Trending Topics**
Themes or topics that keep coming up.

**6. Standout Comments**
2–3 particularly insightful comments worth reading in full (quote them).

Be specific and actionable. Use plain language."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    h = text
    h = re.sub(r"^\*\*(\d+\..+?)\*\*$", r"<h2>\1</h2>", h, flags=re.MULTILINE)
    h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
    h = re.sub(r"^- (.+)$", r"<li>\1</li>", h, flags=re.MULTILINE)
    h = re.sub(r"(<li>.*?</li>\n?)+", lambda m: f"<ul>{m.group()}</ul>", h, flags=re.DOTALL)
    h = re.sub(r"\n{2,}", "</p><p>", h)
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#222">
  <div style="background:linear-gradient(135deg,#c0392b,#e67e22);padding:24px 28px;border-radius:10px;margin-bottom:24px">
    <h1 style="color:#fff;margin:0;font-size:22px">🌋 Eruption Hot Sauce</h1>
    <p style="color:rgba(255,255,255,.85);margin:4px 0 0;font-size:14px">YouTube Comment Digest · {datetime.now().strftime("%B %d, %Y")}</p>
  </div>
  <div style="line-height:1.65"><p>{h}</p></div>
  <p style="font-size:12px;color:#aaa;margin-top:32px">Generated automatically · reply to unsubscribe</p>
</body></html>"""


def send_email(subject: str, analysis: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(analysis, "plain"))
    msg.attach(MIMEText(_md_to_html(analysis), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_FROM, EMAIL_PASSWORD)
        s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Starting YouTube Comment Digest")

    print(f"Fetching videos for channel {CHANNEL_ID} …")
    videos = fetch_recent_videos()
    if not videos:
        print("No videos found — check YOUTUBE_CHANNEL_ID.")
        sys.exit(1)
    print(f"  {len(videos)} videos found")

    video_comments: dict = {}
    for vid_id, title in videos:
        print(f"  Fetching comments: {title[:70]} …")
        comments = fetch_comments(vid_id)
        if comments:
            video_comments[title] = comments
            print(f"    {len(comments)} comments")

    if not video_comments:
        print("No comments collected (comments may be disabled). Exiting.")
        sys.exit(0)

    total = sum(len(c) for c in video_comments.values())
    print(f"\nAnalyzing {total} comments with Claude …")
    analysis = analyze(video_comments)

    subject = f"YouTube Comment Digest — {datetime.now().strftime('%B %d, %Y')}"
    print(f"Sending email to {EMAIL_TO} …")
    send_email(subject, analysis)
    print("Done.")


if __name__ == "__main__":
    main()
