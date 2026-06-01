#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches comments from your recent YouTube videos, analyses sentiment & improvement
opportunities with Claude AI, and emails you a formatted HTML summary.

Usage:
    python3 youtube_digest.py

Required environment variables (copy .env.example → .env and fill in):
    YOUTUBE_API_KEY      – YouTube Data API v3 key
    YOUTUBE_CHANNEL_ID   – Your channel ID (UCxxxxxxxxxx) or handle (@yourhandle)
    ANTHROPIC_API_KEY    – Anthropic / Claude API key
    EMAIL_TO             – Recipient email address
    EMAIL_FROM           – Sender Gmail address
    EMAIL_APP_PASSWORD   – Gmail App Password (not your regular password)

Schedule with cron (weekly on Mondays at 8 AM):
    0 8 * * 1 cd /path/to/eruption-hot-sauce && python3 youtube_digest.py
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

# ── Configuration ─────────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY", "")
CHANNEL_ID         = os.getenv("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
EMAIL_TO           = os.getenv("EMAIL_TO", "")
EMAIL_FROM         = os.getenv("EMAIL_FROM", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

MAX_VIDEOS           = 10   # recent uploads to analyse
MAX_COMMENTS_PER_VID = 50   # comments fetched per video

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"

# ── YouTube helpers ────────────────────────────────────────────────────────────

def resolve_channel_id(raw: str) -> str:
    """
    Accept a channel ID (UCxxx), a @handle, or a plain search term
    and return the canonical UCxxx channel ID.
    """
    if raw.startswith("UC"):
        return raw

    # Handle @handle or plain username → search API
    resp = requests.get(
        f"{YOUTUBE_BASE}/search",
        params={
            "part": "snippet",
            "q": raw.lstrip("@"),
            "type": "channel",
            "maxResults": 1,
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise ValueError(f"Could not find a YouTube channel matching: {raw!r}")
    found = items[0]["snippet"]["channelTitle"]
    cid = items[0]["id"]["channelId"]
    print(f"  Resolved '{raw}' → {found} ({cid})")
    return cid


def fetch_recent_videos(channel_id: str) -> list[dict]:
    """Return the MAX_VIDEOS most recent uploads for the channel."""
    # 1. Get the uploads playlist ID
    resp = requests.get(
        f"{YOUTUBE_BASE}/channels",
        params={
            "part": "contentDetails,snippet",
            "id": channel_id,
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("items"):
        raise ValueError(f"No channel found with ID: {channel_id}")

    channel_name = data["items"][0]["snippet"]["title"]
    uploads_pl   = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"  Channel: {channel_name}")

    # 2. List videos in the uploads playlist
    resp = requests.get(
        f"{YOUTUBE_BASE}/playlistItems",
        params={
            "part": "snippet",
            "playlistId": uploads_pl,
            "maxResults": MAX_VIDEOS,
            "key": YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    return [
        {
            "video_id":     item["snippet"]["resourceId"]["videoId"],
            "title":        item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"][:10],
        }
        for item in items
    ], channel_name


def fetch_comments(video_id: str) -> list[dict]:
    """Fetch top-level comments for a single video (returns [] if disabled)."""
    try:
        resp = requests.get(
            f"{YOUTUBE_BASE}/commentThreads",
            params={
                "part": "snippet",
                "videoId": video_id,
                "maxResults": MAX_COMMENTS_PER_VID,
                "order": "relevance",
                "key": YOUTUBE_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if exc.response.status_code in (403, 404):
            return []   # comments disabled or video private
        raise

    return [
        {
            "author": item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
            "text":   item["snippet"]["topLevelComment"]["snippet"]["textOriginal"].strip(),
            "likes":  item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
        }
        for item in resp.json().get("items", [])
    ]

# ── Claude analysis ────────────────────────────────────────────────────────────

def analyse_with_claude(video_data: list[dict]) -> str:
    """Send comment corpus to Claude and return a structured markdown analysis."""
    sections = []
    for vd in video_data:
        if not vd["comments"]:
            continue
        header = f'### "{vd["title"]}" (published {vd["published_at"]})'
        rows   = [
            f'- [{c["likes"]} 👍] {c["text"][:250]}'
            for c in vd["comments"][:25]
        ]
        sections.append(header + "\n" + "\n".join(rows))

    if not sections:
        return "_No comments were found across the analysed videos._"

    corpus = "\n\n".join(sections)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        system=(
            "You are an expert YouTube content strategist. Be direct, specific, and actionable. "
            "Use bullet points. Avoid vague generalities."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "Analyse the YouTube comments below from my recent videos and produce a "
                    "digest with exactly these five sections:\n\n"
                    "## 1. Overall Sentiment\n"
                    "Positive / Neutral / Negative breakdown (e.g. 70% / 20% / 10%) "
                    "with a one-sentence summary of the general mood.\n\n"
                    "## 2. What Viewers Love\n"
                    "Top 4–5 things the audience praises most (with examples).\n\n"
                    "## 3. Pain Points & Criticism\n"
                    "Top 4–5 recurring complaints or constructive criticisms.\n\n"
                    "## 4. Actionable Improvements\n"
                    "Exactly 5 specific, prioritised improvements to apply in the next video.\n\n"
                    "## 5. Notable Comments\n"
                    "2–3 standout quotes worth reading (copy verbatim, note the video title).\n\n"
                    "---\n"
                    f"{corpus}"
                ),
            }
        ],
    )
    return msg.content[0].text

# ── Email builder ──────────────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """Minimal Markdown → HTML (headers, bold, bullets, line breaks)."""
    lines, out = text.split("\n"), []
    for line in lines:
        if line.startswith("## "):
            out.append(f'<h3 style="color:#c0392b;margin-top:20px">{line[3:]}</h3>')
        elif line.startswith("### "):
            out.append(f'<h4 style="color:#555;margin-top:14px">{line[4:]}</h4>')
        elif line.startswith("- ") or line.startswith("* "):
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line[2:])
            out.append(f'<li style="margin-bottom:6px">{content}</li>')
        elif line.strip() == "---":
            out.append("<hr style='border:none;border-top:1px solid #eee;margin:16px 0'>")
        elif line.strip():
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
            out.append(f'<p style="margin:6px 0">{content}</p>')
    # Wrap consecutive <li> items in <ul>
    html = "\n".join(out)
    html = re.sub(r'((?:<li[^>]*>.*?</li>\n?)+)', r'<ul style="padding-left:20px">\1</ul>', html)
    return html


def build_html_email(analysis: str, video_data: list[dict], channel_name: str) -> str:
    video_rows = "".join(
        f'<tr style="background:{"#f9f9f9" if i%2 else "#fff"}">'
        f'<td style="padding:6px 10px">{vd["title"][:70]}</td>'
        f'<td style="padding:6px 10px;color:#888;font-size:13px">{vd["published_at"]}</td>'
        f'<td style="padding:6px 10px;text-align:center">{len(vd["comments"])}</td>'
        f'</tr>'
        for i, vd in enumerate(video_data)
    )

    date_str     = datetime.now().strftime("%B %d, %Y")
    html_analysis = _md_to_html(analysis)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:20px;background:#f0f0f0;font-family:Arial,Helvetica,sans-serif">
  <div style="max-width:680px;margin:auto;background:#fff;border-radius:10px;overflow:hidden;
              box-shadow:0 2px 12px rgba(0,0,0,.12)">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#c0392b,#e74c3c);padding:28px 32px">
      <h1 style="color:#fff;margin:0;font-size:24px;letter-spacing:-0.5px">
        YouTube Comment Digest
      </h1>
      <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:14px">
        {channel_name} &bull; {date_str}
      </p>
    </div>

    <div style="padding:28px 32px">

      <!-- Videos table -->
      <h2 style="color:#333;font-size:16px;margin:0 0 12px;text-transform:uppercase;
                 letter-spacing:1px;font-weight:700">Videos Analysed</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:28px">
        <thead>
          <tr style="background:#c0392b;color:#fff">
            <th style="padding:8px 10px;text-align:left">Title</th>
            <th style="padding:8px 10px;text-align:left">Published</th>
            <th style="padding:8px 10px">Comments</th>
          </tr>
        </thead>
        <tbody>{video_rows}</tbody>
      </table>

      <!-- AI Analysis -->
      <h2 style="color:#333;font-size:16px;margin:0 0 16px;text-transform:uppercase;
                 letter-spacing:1px;font-weight:700">AI Analysis</h2>
      <div style="font-size:15px;line-height:1.7;color:#333">
        {html_analysis}
      </div>

      <hr style="border:none;border-top:1px solid #eee;margin:28px 0 16px">
      <p style="color:#aaa;font-size:12px;margin:0;text-align:center">
        Generated by YouTube Comment Digest &bull; Powered by Claude AI
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(subject: str, html_body: str, text_body: str) -> None:
    """Send via Gmail SMTP SSL."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html",  "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        print(f"  Email sent to {EMAIL_TO}")

# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    # Load .env if present (simple parser, no dependency on python-dotenv)
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))
        # Re-read after loading .env
        global YOUTUBE_API_KEY, CHANNEL_ID, ANTHROPIC_API_KEY
        global EMAIL_TO, EMAIL_FROM, EMAIL_APP_PASSWORD
        YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY", "")
        CHANNEL_ID         = os.getenv("YOUTUBE_CHANNEL_ID", "")
        ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
        EMAIL_TO           = os.getenv("EMAIL_TO", "")
        EMAIL_FROM         = os.getenv("EMAIL_FROM", "")
        EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

    missing = [k for k, v in {
        "YOUTUBE_API_KEY":    YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
        "EMAIL_TO":           EMAIL_TO,
        "EMAIL_FROM":         EMAIL_FROM,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
    }.items() if not v]

    if missing:
        print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in all values.")
        sys.exit(1)

    print("=" * 55)
    print("  YouTube Comment Digest")
    print("=" * 55)

    print("\n[1/4] Resolving channel …")
    cid = resolve_channel_id(CHANNEL_ID)

    print("\n[2/4] Fetching recent videos & comments …")
    videos, channel_name = fetch_recent_videos(cid)
    video_data = []
    for v in videos:
        comments = fetch_comments(v["video_id"])
        print(f"  {v['title'][:55]:<55} → {len(comments)} comments")
        video_data.append({**v, "comments": comments})

    total_comments = sum(len(v["comments"]) for v in video_data)
    print(f"\n  Total comments fetched: {total_comments}")

    print("\n[3/4] Analysing with Claude …")
    analysis = analyse_with_claude(video_data)

    print("\n[4/4] Sending email …")
    subject   = f"YouTube Comment Digest — {datetime.now().strftime('%b %d, %Y')}"
    html_body = build_html_email(analysis, video_data, channel_name)
    send_email(subject, html_body, analysis)

    print("\nDone! Check your inbox.")


if __name__ == "__main__":
    main()
