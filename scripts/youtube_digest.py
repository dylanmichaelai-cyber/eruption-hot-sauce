#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel, analyzes sentiment and
improvement opportunities using Claude, then emails a summary to you.

Setup:
  export YOUTUBE_API_KEY="AIza..."
  export YOUTUBE_CHANNEL_ID="UCxxxxxxxxxxxxxxxx"    # Your channel ID
  export ANTHROPIC_API_KEY="sk-ant-..."
  export EMAIL_FROM="you@gmail.com"                  # Gmail address (needs App Password)
  export EMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"   # Gmail App Password
  export EMAIL_TO="you@gmail.com"                    # Recipient

Cron (run every Monday at 8am):
  0 8 * * 1  cd /path/to/project && python3 scripts/youtube_digest.py
"""

import os
import sys
import json
import smtplib
import textwrap
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_FROM         = os.environ.get("EMAIL_FROM", "")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "")
EMAIL_TO           = os.environ.get("EMAIL_TO", EMAIL_FROM)

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"
MAX_VIDEOS   = 10       # most-recent videos to scan
COMMENTS_PER_VIDEO = 50 # top-level comments per video

# ── YouTube helpers ───────────────────────────────────────────────────────────

def yt_get(endpoint: str, params: dict) -> dict:
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YOUTUBE_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_recent_videos(channel_id: str, days: int = 30) -> list[dict]:
    """Return up to MAX_VIDEOS video dicts published in the last `days` days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    data = yt_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "publishedAfter": cutoff,
        "maxResults": MAX_VIDEOS,
    })
    videos = []
    for item in data.get("items", []):
        videos.append({
            "id":      item["id"]["videoId"],
            "title":   item["snippet"]["title"],
            "date":    item["snippet"]["publishedAt"][:10],
        })
    return videos


def get_comments(video_id: str) -> list[str]:
    """Return a list of top-level comment text strings for a video."""
    try:
        data = yt_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": COMMENTS_PER_VIDEO,
            "textFormat": "plainText",
        })
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return []   # comments disabled
        raise
    comments = []
    for item in data.get("items", []):
        text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        comments.append(text.strip())
    return comments


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyse_with_claude(video_data: list[dict]) -> str:
    """
    video_data: [{"title": str, "date": str, "comments": [str, ...]}, ...]
    Returns a structured analysis as plain text.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    summary_input = []
    for v in video_data:
        if not v["comments"]:
            continue
        block = f"Video: \"{v['title']}\" ({v['date']})\n"
        block += "\n".join(f"  - {c}" for c in v["comments"][:30])
        summary_input.append(block)

    if not summary_input:
        return "No comments found in the selected time window."

    prompt = textwrap.dedent(f"""
        You are a YouTube channel analyst. Below are recent viewer comments
        across several videos. Please provide a concise report with these sections:

        1. **Overall Viewer Sentiment** – one paragraph on how viewers feel
           about the channel overall (positive, negative, mixed), with 2-3
           specific examples drawn directly from the comments.

        2. **What Viewers Love** – 3-5 bullet points on what's resonating well.

        3. **Improvement Opportunities** – 3-5 actionable suggestions the creator
           should focus on, grounded in the comments.

        4. **Notable Trends** – any repeated themes, requests, or questions that
           appear across multiple videos.

        5. **Quick Stats** – rough estimate of sentiment breakdown
           (e.g. 70% positive, 20% neutral, 10% negative).

        Keep the tone helpful, direct, and creator-focused.

        --- COMMENT DATA ---
        {chr(10).join(summary_input)}
    """).strip()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, body_plain: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body_plain, "plain"))
    msg.attach(MIMEText(body_html,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def build_html(analysis: str, video_data: list[dict], run_date: str) -> tuple[str, str]:
    total_comments = sum(len(v["comments"]) for v in video_data)
    video_count    = len([v for v in video_data if v["comments"]])

    # Convert markdown-style bold (**text**) to <strong>
    import re
    html_analysis = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", analysis)
    html_analysis = html_analysis.replace("\n", "<br>")

    video_rows = "".join(
        f"<tr><td style='padding:4px 8px'>{v['title']}</td>"
        f"<td style='padding:4px 8px;text-align:center'>{v['date']}</td>"
        f"<td style='padding:4px 8px;text-align:center'>{len(v['comments'])}</td></tr>"
        for v in video_data
    )

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;color:#222">
  <div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0">
    <h1 style="color:#fff;margin:0;font-size:22px">🔥 YouTube Comment Digest</h1>
    <p style="color:#fcc;margin:4px 0 0">Generated {run_date}</p>
  </div>
  <div style="background:#f9f9f9;padding:16px;border:1px solid #ddd">
    <p><strong>Videos scanned:</strong> {video_count} &nbsp;|&nbsp;
       <strong>Total comments:</strong> {total_comments}</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#eee">
          <th style="padding:4px 8px;text-align:left">Video</th>
          <th style="padding:4px 8px">Date</th>
          <th style="padding:4px 8px">Comments</th>
        </tr>
      </thead>
      <tbody>{video_rows}</tbody>
    </table>
  </div>
  <div style="padding:20px;border:1px solid #ddd;border-top:none;background:#fff">
    <h2 style="color:#c0392b;font-size:18px">Analysis</h2>
    <p style="line-height:1.7">{html_analysis}</p>
  </div>
  <div style="background:#222;color:#aaa;padding:12px;font-size:12px;text-align:center;
              border-radius:0 0 8px 8px">
    Eruption Hot Sauce · YouTube Digest · Auto-generated report
  </div>
</body></html>"""

    plain = f"YouTube Comment Digest — {run_date}\n\n" \
            f"Videos scanned: {video_count} | Total comments: {total_comments}\n\n" \
            f"{analysis}"

    return plain, html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    missing = [v for v in ("YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID",
                            "ANTHROPIC_API_KEY", "EMAIL_FROM",
                            "EMAIL_APP_PASSWORD") if not globals()[v]]
    if missing:
        print(f"ERROR: missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    print("Fetching recent videos…")
    videos = get_recent_videos(YOUTUBE_CHANNEL_ID)
    if not videos:
        print("No videos found in the last 30 days. Exiting.")
        return

    print(f"Found {len(videos)} video(s). Fetching comments…")
    video_data = []
    for v in videos:
        comments = get_comments(v["id"])
        print(f"  {v['title'][:60]}… — {len(comments)} comment(s)")
        video_data.append({**v, "comments": comments})

    print("Analysing with Claude…")
    analysis = analyse_with_claude(video_data)

    run_date = datetime.now().strftime("%B %d, %Y")
    plain, html = build_html(analysis, video_data, run_date)

    subject = f"YouTube Comment Digest — {run_date}"
    print(f"Sending email to {EMAIL_TO}…")
    send_email(subject, plain, html)
    print("Done! Digest sent.")


if __name__ == "__main__":
    main()
