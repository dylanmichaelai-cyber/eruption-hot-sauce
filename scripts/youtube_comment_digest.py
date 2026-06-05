#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches comments from your YouTube channel, analyses sentiment and improvement
areas with Claude, then emails you a summary.

Usage:
  python3 scripts/youtube_comment_digest.py

Required env vars (or edit the CONFIG block below):
  YOUTUBE_API_KEY   - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID - Your channel ID (e.g. UCxxxxxxxxxxxxxxxxxxxxxxxx)
  ANTHROPIC_API_KEY  - Anthropic API key for Claude analysis
  GMAIL_FROM         - Gmail address you're sending FROM (needs App Password)
  GMAIL_APP_PASSWORD - Gmail App Password (not your normal password)
  DIGEST_RECIPIENT   - Email address to receive the digest
"""

import os
import json
import smtplib
import textwrap
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import anthropic

# ─── CONFIG ──────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY",    "AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")   # e.g. UCxxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "")
GMAIL_FROM         = os.getenv("GMAIL_FROM",         "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
DIGEST_RECIPIENT   = os.getenv("DIGEST_RECIPIENT",   "d.mcderm80@gmail.com")

MAX_VIDEOS    = 10   # recent videos to scan
MAX_COMMENTS  = 50   # comments per video
# ─────────────────────────────────────────────────────────────────────────────


def yt_get(endpoint: str, params: dict) -> dict:
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_recent_videos(channel_id: str) -> list[dict]:
    """Return up to MAX_VIDEOS recent uploads with id + title."""
    # Get the uploads playlist ID
    data = yt_get("channels", {"part": "contentDetails", "id": channel_id})
    items = data.get("items", [])
    if not items:
        raise ValueError(f"Channel '{channel_id}' not found or has no uploads.")
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    page_token = None
    while len(videos) < MAX_VIDEOS:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": min(MAX_VIDEOS - len(videos), 50),
        }
        if page_token:
            params["pageToken"] = page_token
        data = yt_get("playlistItems", params)
        for item in data.get("items", []):
            snip = item["snippet"]
            videos.append({
                "id":    snip["resourceId"]["videoId"],
                "title": snip["title"],
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos[:MAX_VIDEOS]


def fetch_comments(video_id: str) -> list[str]:
    """Return up to MAX_COMMENTS top-level comment texts for a video."""
    comments = []
    page_token = None
    while len(comments) < MAX_COMMENTS:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": min(MAX_COMMENTS - len(comments), 100),
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            data = yt_get("commentThreads", params)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                # Comments disabled on this video
                break
            raise
        for item in data.get("items", []):
            text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(text.strip())
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return comments[:MAX_COMMENTS]


def analyse_with_claude(video_title: str, comments: list[str]) -> str:
    """Ask Claude to summarise sentiment and improvement areas."""
    if not comments:
        return "No comments available for this video."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    comment_block = "\n".join(f"- {c}" for c in comments)

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": textwrap.dedent(f"""
                You are a YouTube growth coach. Below are audience comments for a video titled:
                "{video_title}"

                COMMENTS:
                {comment_block}

                Write a concise analysis (3–5 short paragraphs) covering:
                1. Overall sentiment (positive / mixed / negative) with evidence.
                2. What viewers loved most.
                3. Specific, actionable improvements suggested by the comments.
                4. Any recurring questions or topics that could inspire future content.

                Be direct, constructive, and skip fluff.
            """).strip(),
        }],
    )
    return message.content[0].text.strip()


def build_email_html(results: list[dict]) -> tuple[str, str]:
    """Build (plain_text, html) for the digest email."""
    now = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject = f"YouTube Comment Digest — {now}"

    # ── plain text ────────────────────────────────────────────────────────────
    plain_parts = [f"YouTube Comment Digest  |  {now}\n{'='*50}\n"]
    for r in results:
        plain_parts.append(f"\n📹 {r['title']}")
        plain_parts.append(f"   Comments analysed: {r['comment_count']}")
        plain_parts.append(f"\n{r['analysis']}\n")
        plain_parts.append("-" * 50)

    plain_text = "\n".join(plain_parts)

    # ── html ──────────────────────────────────────────────────────────────────
    video_blocks = ""
    for r in results:
        analysis_html = "".join(
            f"<p style='margin:8px 0;color:#374151;'>{p}</p>"
            for p in r["analysis"].split("\n\n")
            if p.strip()
        )
        video_blocks += f"""
        <div style='background:#fff;border:1px solid #e5e7eb;border-radius:8px;
                    padding:20px;margin-bottom:24px;'>
          <h2 style='margin:0 0 4px;font-size:16px;color:#111827;'>{r['title']}</h2>
          <p style='margin:0 0 14px;font-size:12px;color:#6b7280;'>
            {r['comment_count']} comment{"s" if r["comment_count"] != 1 else ""} analysed
          </p>
          {analysis_html}
        </div>
        """

    html = f"""
    <html><body style='font-family:sans-serif;max-width:680px;margin:0 auto;padding:24px;
                       background:#f9fafb;color:#111827;'>
      <h1 style='font-size:20px;color:#dc2626;margin-bottom:4px;'>
        🌋 YouTube Comment Digest
      </h1>
      <p style='color:#6b7280;font-size:13px;margin-top:0;margin-bottom:24px;'>{now}</p>
      {video_blocks}
      <p style='font-size:11px;color:#9ca3af;text-align:center;margin-top:32px;'>
        Generated by eruption-hot-sauce digest script
      </p>
    </body></html>
    """

    return subject, plain_text, html


def send_email(subject: str, plain_text: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_FROM
    msg["To"]      = DIGEST_RECIPIENT

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html,       "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_FROM, [DIGEST_RECIPIENT], msg.as_string())

    print(f"✅  Email sent to {DIGEST_RECIPIENT}")


def main():
    if not YOUTUBE_CHANNEL_ID:
        raise SystemExit(
            "❌  YOUTUBE_CHANNEL_ID is not set.\n"
            "    Find it at: https://www.youtube.com/account_advanced\n"
            "    Then export it:  export YOUTUBE_CHANNEL_ID=UCxxxxxxxxxx"
        )
    if not ANTHROPIC_API_KEY:
        raise SystemExit("❌  ANTHROPIC_API_KEY is not set.")
    if not GMAIL_FROM or not GMAIL_APP_PASSWORD:
        raise SystemExit(
            "❌  GMAIL_FROM and GMAIL_APP_PASSWORD are not set.\n"
            "    Create an App Password at: https://myaccount.google.com/apppasswords"
        )

    print(f"📡  Fetching up to {MAX_VIDEOS} recent videos for channel {YOUTUBE_CHANNEL_ID}…")
    videos = fetch_recent_videos(YOUTUBE_CHANNEL_ID)
    print(f"    Found {len(videos)} video(s).")

    results = []
    for video in videos:
        print(f"\n💬  Fetching comments for: {video['title']}")
        comments = fetch_comments(video["id"])
        print(f"    {len(comments)} comment(s) retrieved.")

        if comments:
            print("    🤖  Analysing with Claude…")
            analysis = analyse_with_claude(video["title"], comments)
        else:
            analysis = "Comments are disabled or unavailable for this video."

        results.append({
            "title":         video["title"],
            "comment_count": len(comments),
            "analysis":      analysis,
        })

    print("\n📧  Building and sending email digest…")
    subject, plain_text, html = build_email_html(results)
    send_email(subject, plain_text, html)
    print("Done.")


if __name__ == "__main__":
    main()
