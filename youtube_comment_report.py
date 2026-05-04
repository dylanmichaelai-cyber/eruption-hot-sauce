#!/usr/bin/env python3
"""
YouTube Comment Analysis Routine — Eruption Hot Sauce
Fetches recent video comments, summarizes audience sentiment with Claude,
and emails the report via Gmail SMTP.

Required env vars:
  YOUTUBE_API_KEY       — YouTube Data API v3 key
  ANTHROPIC_API_KEY     — Anthropic API key for Claude
  YOUTUBE_CHANNEL_ID    — Your channel ID (e.g. UCxxxxxxx)
                          OR set YOUTUBE_CHANNEL_NAME to auto-discover it
  EMAIL_FROM            — Gmail address to send from
  EMAIL_TO              — Address to receive the report
  EMAIL_APP_PASSWORD    — Gmail App Password (not your main password)
                          See: https://myaccount.google.com/apppasswords

Optional env vars:
  VIDEOS_TO_SCAN        — Number of recent videos to scan (default: 5)
  COMMENTS_PER_VIDEO    — Max comments per video (default: 100)
  DAYS_BACK             — How far back to look for videos (default: 30)
"""

import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Config ────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
CHANNEL_ID         = os.getenv("YOUTUBE_CHANNEL_ID")
CHANNEL_NAME       = os.getenv("YOUTUBE_CHANNEL_NAME", "Eruption Hot Sauce")

EMAIL_FROM         = os.getenv("EMAIL_FROM")
EMAIL_TO           = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

VIDEOS_TO_SCAN     = int(os.getenv("VIDEOS_TO_SCAN", "5"))
COMMENTS_PER_VIDEO = int(os.getenv("COMMENTS_PER_VIDEO", "100"))
DAYS_BACK          = int(os.getenv("DAYS_BACK", "30"))

YT_BASE = "https://www.googleapis.com/youtube/v3"

# ── YouTube helpers ───────────────────────────────────────────────────────────

def yt_get(endpoint, **params):
    """GET a YouTube Data API endpoint, raise on error."""
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def resolve_channel_id():
    """Look up channel ID by name when YOUTUBE_CHANNEL_ID is not set."""
    if CHANNEL_ID:
        return CHANNEL_ID

    print(f"YOUTUBE_CHANNEL_ID not set — searching for '{CHANNEL_NAME}'...")
    data = yt_get("search", part="snippet", q=CHANNEL_NAME, type="channel", maxResults=5)

    for item in data.get("items", []):
        title = item["snippet"]["title"]
        cid   = item["snippet"]["channelId"]
        if CHANNEL_NAME.lower() in title.lower():
            print(f"  Found: '{title}' → {cid}")
            print(f"  Tip: set YOUTUBE_CHANNEL_ID={cid} to skip this lookup next time.\n")
            return cid

    items = data.get("items", [])
    if not items:
        raise ValueError(f"No channel found matching '{CHANNEL_NAME}'.")

    cid = items[0]["snippet"]["channelId"]
    print(f"  Using first result: '{items[0]['snippet']['title']}' → {cid}\n")
    return cid


def fetch_recent_videos(channel_id):
    """Return up to VIDEOS_TO_SCAN recent videos from the channel."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = yt_get(
        "search",
        part="snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=VIDEOS_TO_SCAN,
        publishedAfter=published_after,
    )

    return [
        {
            "id":           item["id"]["videoId"],
            "title":        item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
    ]


def fetch_comments(video_id):
    """Return top-level comments for a video, ordered by relevance."""
    try:
        data = yt_get(
            "commentThreads",
            part="snippet",
            videoId=video_id,
            maxResults=COMMENTS_PER_VIDEO,
            order="relevance",
            textFormat="plainText",
        )
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            print(f"    Comments disabled for this video.")
        else:
            print(f"    Warning fetching comments: {e}")
        return []

    comments = []
    for item in data.get("items", []):
        snip = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "text":   snip["textDisplay"],
            "likes":  snip["likeCount"],
            "author": snip["authorDisplayName"],
        })
    return comments

# ── Claude analysis ───────────────────────────────────────────────────────────

def build_comment_text(videos_with_comments):
    lines = []
    for v in videos_with_comments:
        lines.append(f"\n### {v['title']}  (published {v['published_at'][:10]})")
        if not v["comments"]:
            lines.append("  (no comments)")
            continue
        for i, c in enumerate(v["comments"][:60], 1):
            lines.append(f"  {i}. [{c['likes']} ♥]  {c['text'][:400]}")
    return "\n".join(lines)


def analyze_with_claude(videos_with_comments):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    comment_block = build_comment_text(videos_with_comments)
    total = sum(len(v["comments"]) for v in videos_with_comments)

    prompt = f"""You are a YouTube content strategist reviewing audience feedback for the **Eruption Hot Sauce** channel.

Below are {total} comments from {len(videos_with_comments)} recent video(s). Write a concise, actionable report with these sections:

## 1. Overall Sentiment
One paragraph: how does the audience generally feel?

## 2. What Viewers Love
3–5 bullet points — recurring praise, favourite moments, things that resonate.

## 3. Constructive Criticism & Areas to Improve
3–5 bullet points — complaints, suggestions, or gaps viewers notice.

## 4. Standout Comments
2–3 notable quotes worth reading (include the author name).

## 5. Actionable Recommendations
3–5 concrete things the creator should do next, based purely on this feedback.

Keep the tone warm and direct. Use markdown formatting.

--- COMMENT DATA ---
{comment_block}
"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text

# ── Email ─────────────────────────────────────────────────────────────────────

def md_to_html(text):
    """Lightweight markdown → HTML for the email body."""
    h = text
    h = re.sub(r"^## (.+)$",     r"<h2>\1</h2>",            h, flags=re.MULTILINE)
    h = re.sub(r"^### (.+)$",    r"<h3>\1</h3>",            h, flags=re.MULTILINE)
    h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>",    h)
    h = re.sub(r"^[-•] (.+)$",   r"<li>\1</li>",            h, flags=re.MULTILINE)
    h = re.sub(r"(<li>.*?</li>\n?)+", r"<ul>\g<0></ul>",    h, flags=re.DOTALL)
    h = re.sub(r"\n\n+",          "</p><p>",                 h)
    return f"<p>{h}</p>"


def build_html_email(summary, total_comments, video_count, today):
    return f"""<!DOCTYPE html>
<html>
<head>
<style>
  body   {{ font-family: Georgia, serif; max-width: 680px; margin: auto; padding: 24px; color: #222; }}
  h1     {{ color: #c0392b; }}
  h2     {{ color: #c0392b; border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  h3     {{ color: #555; }}
  ul     {{ padding-left: 20px; }}
  li     {{ margin-bottom: 6px; }}
  .meta  {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
  .footer{{ color: #aaa; font-size: 11px; margin-top: 32px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
  <h1>Eruption Hot Sauce — YouTube Comment Report</h1>
  <p class="meta">Generated {today} &nbsp;|&nbsp; {total_comments} comments across {video_count} video(s)</p>
  {md_to_html(summary)}
  <p class="footer">Auto-generated by the YouTube Comment Analysis routine.</p>
</body>
</html>"""


def send_email(subject, plain_text, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    print(f"  Report emailed to {EMAIL_TO}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("═" * 52)
    print("  YouTube Comment Analysis — Eruption Hot Sauce")
    print("═" * 52 + "\n")

    missing = [name for name, val in [
        ("YOUTUBE_API_KEY",   YOUTUBE_API_KEY),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ] if not val]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    channel_id = resolve_channel_id()

    print(f"Fetching last {VIDEOS_TO_SCAN} video(s) from the past {DAYS_BACK} days...")
    videos = fetch_recent_videos(channel_id)
    if not videos:
        sys.exit("No videos found in the specified window. Try increasing DAYS_BACK.")

    print(f"Found {len(videos)} video(s). Fetching comments...\n")
    videos_with_comments = []
    for v in videos:
        print(f"  ▶ {v['title']}")
        comments = fetch_comments(v["id"])
        print(f"    {len(comments)} comment(s)")
        videos_with_comments.append({**v, "comments": comments})

    total_comments = sum(len(v["comments"]) for v in videos_with_comments)
    print(f"\nTotal comments collected: {total_comments}\n")

    if total_comments == 0:
        sys.exit("No comments found. Nothing to analyse.")

    print("Analysing with Claude...\n")
    summary = analyze_with_claude(videos_with_comments)

    today = datetime.now().strftime("%B %d, %Y")
    print("─" * 52)
    print(summary)
    print("─" * 52 + "\n")

    # Save local copy
    report_path = "comment_report.md"
    with open(report_path, "w") as f:
        f.write(f"# YouTube Comment Report — {today}\n\n")
        f.write(f"_{total_comments} comments across {len(videos_with_comments)} video(s)_\n\n")
        f.write(summary)
    print(f"Report saved to {report_path}")

    if EMAIL_FROM and EMAIL_TO and EMAIL_APP_PASSWORD:
        print("Sending email...")
        subject   = f"YouTube Comment Report — {today}"
        html_body = build_html_email(summary, total_comments, len(videos_with_comments), today)
        send_email(subject, summary, html_body)
    else:
        print("Email not sent — set EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD to enable.\n")

    print("Done.")


if __name__ == "__main__":
    main()
