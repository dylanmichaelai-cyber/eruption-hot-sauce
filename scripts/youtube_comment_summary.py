#!/usr/bin/env python3
"""
YouTube Comment Summary Routine for ERUPTION Hot Sauce.
Fetches recent video comments, analyzes them with Claude, and saves an HTML report.

The report is saved to scripts/last_report.html — Claude then drafts the email
via the connected Gmail account (no SMTP credentials needed).

Usage:
    python scripts/youtube_comment_summary.py
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env from this script's directory
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

try:
    import anthropic
    from googleapiclient.discovery import build
except ImportError:
    print("Missing dependencies. Run: pip install -r scripts/requirements.txt")
    sys.exit(1)

YOUTUBE_API_KEY        = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID     = os.getenv("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY      = os.getenv("ANTHROPIC_API_KEY")
DAYS_TO_LOOK_BACK      = int(os.getenv("DAYS_TO_LOOK_BACK", "7"))
MAX_VIDEOS             = int(os.getenv("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "100"))

REPORT_PATH = Path(__file__).parent / "last_report.html"
META_PATH   = Path(__file__).parent / "last_report_meta.json"


# ─────────────────────────────────────────────────────────
#  YouTube helpers
# ─────────────────────────────────────────────────────────

def get_recent_videos(youtube, channel_id: str, days_back: int, max_videos: int):
    channel_resp = youtube.channels().list(
        part="contentDetails,snippet",
        id=channel_id
    ).execute()

    if not channel_resp.get("items"):
        raise ValueError(f"Channel '{channel_id}' not found. Check YOUTUBE_CHANNEL_ID.")

    channel_name = channel_resp["items"][0]["snippet"]["title"]
    uploads_id   = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    cutoff       = datetime.now(timezone.utc) - timedelta(days=days_back)
    videos       = []
    next_token   = None

    while len(videos) < max_videos:
        resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=min(50, max_videos - len(videos)),
            pageToken=next_token,
        ).execute()

        for item in resp.get("items", []):
            snip = item["snippet"]
            pub  = datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00"))
            if pub < cutoff:
                return videos, channel_name
            videos.append({
                "id":           snip["resourceId"]["videoId"],
                "title":        snip["title"],
                "published_at": pub.strftime("%Y-%m-%d"),
            })

        next_token = resp.get("nextPageToken")
        if not next_token:
            break

    return videos, channel_name


def get_video_comments(youtube, video_id: str, max_comments: int) -> list[dict]:
    comments   = []
    next_token = None

    try:
        while len(comments) < max_comments:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_comments - len(comments)),
                order="relevance",
                pageToken=next_token,
            ).execute()

            for item in resp.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "text":   top["textDisplay"],
                    "likes":  top["likeCount"],
                    "author": top["authorDisplayName"],
                })

            next_token = resp.get("nextPageToken")
            if not next_token:
                break

    except Exception as e:
        print(f"  Warning: could not fetch comments for {video_id}: {e}")

    return comments


# ─────────────────────────────────────────────────────────
#  Claude analysis
# ─────────────────────────────────────────────────────────

def analyze_with_claude(client: anthropic.Anthropic, video_data: list[dict]) -> str:
    sections = []
    for v in video_data:
        if not v["comments"]:
            continue
        lines = "\n".join(
            f"  [{c['likes']} likes] {c['text'][:350]}"
            for c in v["comments"][:60]
        )
        sections.append(
            f"### {v['title']}  (uploaded {v['published_at']})\n"
            f"Comments pulled: {len(v['comments'])}\n{lines}"
        )

    if not sections:
        return "<p>No comments were found in the selected time window.</p>"

    prompt = (
        "You are analyzing YouTube comments for ERUPTION, a premium single-origin volcanic hot sauce brand.\n"
        "Based on the comments below, write a concise actionable report covering:\n\n"
        "1. **Overall Sentiment** – percentage positive / neutral / negative, and the dominant emotional tone.\n"
        "2. **What Viewers Love** – top 3–5 praised things, with one brief quoted example each.\n"
        "3. **Pain Points & Criticisms** – top 3–5 recurring issues, with one brief quoted example each.\n"
        "4. **Actionable Improvements** – a prioritised list of concrete things to change or do more of.\n"
        "5. **Trending Topics** – emerging questions or themes showing up repeatedly.\n"
        "6. **Standout Comments** – 2–3 high-value comments worth the creator reading directly.\n\n"
        "Format the entire response as clean inner HTML (no <html>/<body> tags).\n"
        "Use <h2> for section headings, <ul><li> for lists, <blockquote> for quoted comments.\n"
        "Be direct and specific — avoid vague generalisations.\n\n"
        "COMMENTS:\n\n" + "\n\n".join(sections)
    )

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ─────────────────────────────────────────────────────────
#  Report builder
# ─────────────────────────────────────────────────────────

def build_html_report(analysis: str, video_data: list[dict], channel_name: str, days: int) -> str:
    today          = datetime.now().strftime("%B %d, %Y")
    total_comments = sum(len(v["comments"]) for v in video_data)
    covered        = [v for v in video_data if v["comments"]]

    video_rows = "".join(
        f'<li><strong>{v["title"]}</strong>'
        f'<span style="color:#888"> · {len(v["comments"])} comments · {v["published_at"]}</span></li>'
        for v in covered
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body{{font-family:Georgia,serif;background:#0a0a0a;color:#e0e0e0;margin:0;padding:20px}}
  .wrap{{max-width:700px;margin:0 auto;background:#111;border:1px solid #2a2a2a;padding:40px 44px}}
  .brand{{font-family:monospace;font-size:26px;letter-spacing:5px;color:#c0392b;font-weight:bold}}
  .subtitle{{color:#666;font-size:13px;margin-top:6px;font-family:monospace;letter-spacing:1px}}
  .stats{{background:#1a1a1a;border-left:3px solid #c0392b;padding:14px 20px;margin:24px 0;font-size:14px}}
  .stats p{{margin:4px 0;color:#999}}
  .stats ul{{margin:8px 0 0;padding-left:20px;line-height:2}}
  h2{{color:#c0392b;font-family:monospace;letter-spacing:2px;font-size:16px;
      border-bottom:1px solid #222;padding-bottom:6px;margin-top:34px}}
  ul{{line-height:1.9;padding-left:20px}}
  blockquote{{border-left:3px solid #c0392b;margin:12px 0;padding:8px 16px;
              background:#1a1a1a;color:#aaa;font-style:italic;font-size:14px}}
  .footer{{margin-top:40px;padding-top:18px;border-top:1px solid #222;
           color:#444;font-size:12px;font-family:monospace}}
  code{{background:#1e1e1e;padding:2px 6px;border-radius:3px;font-size:12px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">ERUPTION<sup style="font-size:14px">®</sup></div>
  <div class="subtitle">YOUTUBE COMMENT INTELLIGENCE · {today}</div>

  <div class="stats">
    <p>Channel: <strong style="color:#ddd">{channel_name}</strong></p>
    <p>Period: last {days} days &nbsp;·&nbsp; Videos: {len(covered)} &nbsp;·&nbsp; Comments analysed: {total_comments}</p>
    <ul>{video_rows}</ul>
  </div>

  {analysis}

  <div class="footer">
    Auto-generated by the Eruption YouTube Comment Routine.<br>
    Re-run: <code>python scripts/youtube_comment_summary.py</code>
  </div>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────

def main():
    required = {
        "YOUTUBE_API_KEY":    YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": YOUTUBE_CHANNEL_ID,
        "ANTHROPIC_API_KEY":  ANTHROPIC_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}")
        print("Fill them in scripts/.env (copy from scripts/.env.example).")
        sys.exit(1)

    print(f"[1/3] Fetching videos from the last {DAYS_TO_LOOK_BACK} days...")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    videos, channel_name = get_recent_videos(
        youtube, YOUTUBE_CHANNEL_ID, DAYS_TO_LOOK_BACK, MAX_VIDEOS
    )

    if not videos:
        print(f"No videos published in the last {DAYS_TO_LOOK_BACK} days. Nothing to report.")
        sys.exit(0)

    print(f"[2/3] Found {len(videos)} video(s) on '{channel_name}'. Fetching comments...")
    video_data = []
    for v in videos:
        print(f"  → {v['title']}")
        comments = get_video_comments(youtube, v["id"], MAX_COMMENTS_PER_VIDEO)
        video_data.append({**v, "comments": comments})
        print(f"     {len(comments)} comments")

    print("[3/3] Analysing with Claude...")
    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    analysis = analyze_with_claude(client, video_data)

    html = build_html_report(analysis, video_data, channel_name, DAYS_TO_LOOK_BACK)
    REPORT_PATH.write_text(html, encoding="utf-8")

    total = sum(len(v["comments"]) for v in video_data)
    subject = f"ERUPTION — YouTube Comment Report · {datetime.now().strftime('%b %d, %Y')}"
    META_PATH.write_text(json.dumps({
        "subject":      subject,
        "channel_name": channel_name,
        "total_comments": total,
        "video_count":  len(video_data),
        "days":         DAYS_TO_LOOK_BACK,
    }))

    print(f"\nReport saved to {REPORT_PATH}")
    print(f"Subject: {subject}")
    print("Ready to draft — ask Claude to send it via Gmail.")


if __name__ == "__main__":
    main()
