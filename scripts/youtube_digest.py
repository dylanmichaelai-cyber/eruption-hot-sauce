#!/usr/bin/env python3
"""
YouTube Comment Digest
======================
Fetches recent comments from your YouTube channel, analyzes them with Claude
(sentiment + improvement tips), and emails the digest to you.

Quick start
-----------
1. Copy scripts/.env.example to scripts/.env and fill in the values.
2. Run:  python3 scripts/youtube_digest.py

Schedule (weekly on Mondays at 9 AM)
-------------------------------------
   0 9 * * 1 cd /path/to/eruption-hot-sauce && python3 scripts/youtube_digest.py
"""

import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Load .env if present (no third-party lib needed) ─────────────────────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def _require(key):
    val = os.environ.get(key, "").strip()
    if not val:
        sys.exit(f"ERROR: environment variable {key!r} is not set. See scripts/.env.example.")
    return val


# ── Config ────────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY        = _require("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID     = _require("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY      = _require("ANTHROPIC_API_KEY")
RECIPIENT_EMAIL        = os.environ.get("RECIPIENT_EMAIL", "d.mcderm80@gmail.com")
SMTP_HOST              = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT              = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER              = os.environ.get("SMTP_USER", RECIPIENT_EMAIL)
SMTP_PASSWORD          = _require("SMTP_PASSWORD")
MAX_VIDEOS             = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))

YT_BASE = "https://www.googleapis.com/youtube/v3"


# ── YouTube helpers ───────────────────────────────────────────────────────────

def _yt_get(endpoint, **params):
    params["key"] = YOUTUBE_API_KEY
    url = f"{YT_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        sys.exit(f"YouTube API error {exc.code} on /{endpoint}: {body[:300]}")


def fetch_recent_videos(channel_id, max_results=10):
    data = _yt_get(
        "search",
        channelId=channel_id,
        part="id,snippet",
        order="date",
        type="video",
        maxResults=max_results,
    )
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]


def fetch_comments(video_id, max_results=50):
    try:
        data = _yt_get(
            "commentThreads",
            videoId=video_id,
            part="snippet",
            order="relevance",
            maxResults=max_results,
            textFormat="plainText",
        )
    except SystemExit:
        return []   # comments disabled (403) or other per-video error
    return [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in data.get("items", [])
    ]


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyze_with_claude(video_comment_data):
    sections = []
    for video in video_comment_data:
        lines = "\n".join(f"  - {c}" for c in video["comments"]) or "  (no comments or comments disabled)"
        sections.append(f"### {video['title']}\n{lines}")
    all_comments = "\n\n".join(sections)

    prompt = f"""You are a YouTube analytics assistant. Below are recent comments from a creator's videos.

{all_comments}

Produce a concise digest with these four sections:

**1. Overall Sentiment**
A short paragraph describing how viewers feel overall (positive / negative / mixed) and the dominant mood.

**2. What Viewers Love**
Bullet list of the top 3-5 themes or moments that viewers consistently praise.

**3. Constructive Criticism**
Bullet list of the top 3-5 recurring complaints, concerns, or suggestions from viewers.

**4. Actionable Improvements**
Numbered list of exactly 5 specific, practical things the creator can do to improve future videos, grounded in the feedback above.

Be direct, specific, and helpful. Base everything strictly on the comments provided."""

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            response = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Claude API error {exc.code}: {exc.read().decode(errors='replace')[:300]}")

    return response["content"][0]["text"]


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_html(analysis, videos):
    def md_to_html(text):
        """Minimal markdown → HTML for bold, bullets, and newlines."""
        import re
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        lines = text.split("\n")
        out, in_list = [], False
        for line in lines:
            if line.lstrip().startswith("- "):
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                out.append(f"<li>{line.lstrip()[2:]}</li>")
            elif line.lstrip().startswith(tuple(f"{i}." for i in range(1, 10))):
                if not in_list:
                    out.append("<ol>")
                    in_list = True
                out.append(f"<li>{line.split('.', 1)[1].strip()}</li>")
            else:
                if in_list:
                    out.append("</ul>" if "<ul>" in "".join(out[-10:]) else "</ol>")
                    in_list = False
                out.append(f"<p>{line}</p>" if line.strip() else "")
        if in_list:
            out.append("</ul>")
        return "\n".join(out)

    video_items = "".join(
        f'<li><a href="https://youtu.be/{v["id"]}" style="color:#c0392b;">'
        f'{v["title"]}</a> '
        f'<span style="color:#999;font-size:12px;">({len(v["comments"])} comments)</span></li>'
        for v in videos
    )
    now = datetime.now(timezone.utc).strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  body {{font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:32px auto;color:#222;line-height:1.6;}}
  h1 {{color:#c0392b;margin-bottom:4px;}}
  h2 {{color:#333;border-bottom:2px solid #f0f0f0;padding-bottom:6px;margin-top:28px;}}
  .meta {{color:#888;font-size:13px;margin-bottom:24px;}}
  .analysis {{background:#fafafa;border-left:4px solid #c0392b;padding:16px 20px;border-radius:0 6px 6px 0;}}
  ul,ol {{padding-left:22px;}}
  li {{margin-bottom:4px;}}
  strong {{color:#111;}}
  footer {{color:#bbb;font-size:11px;margin-top:40px;border-top:1px solid #eee;padding-top:12px;}}
</style>
</head>
<body>
<h1>YouTube Comment Digest</h1>
<p class="meta">Generated {now} &nbsp;·&nbsp; {len(videos)} videos analyzed</p>

<h2>Videos Included</h2>
<ul>{video_items}</ul>

<h2>AI-Powered Analysis</h2>
<div class="analysis">{md_to_html(analysis)}</div>

<footer>
  This digest is generated automatically by your YouTube Comment Digest script.<br>
  To adjust frequency or video count, edit <code>scripts/.env</code>.
</footer>
</body>
</html>"""


def send_email(subject, plain_text, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [RECIPIENT_EMAIL], msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[1/4] Fetching up to {MAX_VIDEOS} recent videos from channel {YOUTUBE_CHANNEL_ID}…")
    videos = fetch_recent_videos(YOUTUBE_CHANNEL_ID, max_results=MAX_VIDEOS)
    if not videos:
        sys.exit("No videos found — double-check YOUTUBE_CHANNEL_ID in scripts/.env")
    print(f"      Found {len(videos)} video(s).")

    print("[2/4] Fetching comments…")
    for v in videos:
        v["comments"] = fetch_comments(v["id"], max_results=MAX_COMMENTS_PER_VIDEO)
        print(f"      {v['title'][:60]!r}: {len(v['comments'])} comment(s)")

    total_comments = sum(len(v["comments"]) for v in videos)
    if total_comments == 0:
        sys.exit("No comments found across any video — nothing to analyze.")

    print(f"[3/4] Analyzing {total_comments} comment(s) with Claude…")
    analysis = analyze_with_claude(videos)

    subject   = f"YouTube Comment Digest — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
    html_body = _build_html(analysis, videos)

    print(f"[4/4] Sending digest to {RECIPIENT_EMAIL}…")
    send_email(subject, analysis, html_body)
    print("Done! Check your inbox.")


if __name__ == "__main__":
    main()
