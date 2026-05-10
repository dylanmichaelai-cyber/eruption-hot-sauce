#!/usr/bin/env python3
"""
YouTube Comment Digest
======================
Fetches recent comments from your YouTube channel, analyzes viewer sentiment
and improvement areas using Claude, then emails you a formatted summary.

Required environment variables:
  YOUTUBE_API_KEY       YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID    Your channel ID  (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)
                        OR set YOUTUBE_CHANNEL_HANDLE (e.g. @YourHandle)
  ANTHROPIC_API_KEY     Anthropic API key
  GMAIL_SENDER          Your Gmail address (used to send the digest)
  GMAIL_APP_PASSWORD    Gmail App Password — NOT your account password.
                        Create one at myaccount.google.com → Security → App passwords
  DIGEST_RECIPIENT      Email address to receive the digest (defaults to GMAIL_SENDER)

Optional:
  DAYS_BACK             How many days of videos to scan (default: 7)
  MAX_VIDEOS            Max videos to pull comments from (default: 10)
  MAX_COMMENTS_PER_VIDEO  Max comments per video (default: 50)
"""

import os
import re
import smtplib
import textwrap
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
DAYS_BACK = int(os.environ.get("DAYS_BACK", 7))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", 10))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", 50))


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def resolve_channel_id(api_key: str) -> str:
    """Return channel ID from env, resolving a handle to an ID if needed."""
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
    if channel_id:
        return channel_id

    handle = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "").strip()
    if not handle:
        raise ValueError(
            "Set YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE in your environment."
        )

    resp = requests.get(
        f"{YOUTUBE_API_BASE}/channels",
        params={"part": "id", "forHandle": handle, "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise ValueError(f"No channel found for handle '{handle}'.")
    return items[0]["id"]


def get_uploads_playlist_id(api_key: str, channel_id: str) -> str:
    """Return the uploads playlist ID for a channel (quota cost: 1 unit)."""
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/channels",
        params={"part": "contentDetails", "id": channel_id, "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise ValueError(f"Channel '{channel_id}' not found.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_recent_videos(api_key: str, uploads_playlist_id: str) -> list[dict]:
    """
    Return up to MAX_VIDEOS recent videos, filtered to the last DAYS_BACK days.
    Falls back to the most recent MAX_VIDEOS if none fall within the window.
    Uses playlistItems (1 quota unit) instead of search (100 units).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    resp = requests.get(
        f"{YOUTUBE_API_BASE}/playlistItems",
        params={
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": MAX_VIDEOS,
            "key": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    videos = []
    for item in items:
        snippet = item["snippet"]
        published = datetime.fromisoformat(
            snippet["publishedAt"].replace("Z", "+00:00")
        )
        videos.append(
            {
                "id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "published": published,
            }
        )

    recent = [v for v in videos if v["published"] >= cutoff]
    return recent if recent else videos  # fallback: return all fetched if none are recent


def get_comments(api_key: str, video_id: str) -> list[str]:
    """Return top-level comment texts for a video. Returns [] if disabled."""
    try:
        resp = requests.get(
            f"{YOUTUBE_API_BASE}/commentThreads",
            params={
                "part": "snippet",
                "videoId": video_id,
                "maxResults": MAX_COMMENTS_PER_VIDEO,
                "order": "relevance",
                "key": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (403, 404):
            return []  # comments disabled or video unavailable
        raise

    items = resp.json().get("items", [])
    return [i["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for i in items]


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def build_prompt(videos: list[dict]) -> str:
    sections = []
    for v in videos:
        age_days = (datetime.now(timezone.utc) - v["published"]).days
        header = f"### {v['title']}  (published {age_days}d ago)"
        if v["comments"]:
            body = "\n".join(f"- {c}" for c in v["comments"])
        else:
            body = "_No comments or comments are disabled._"
        sections.append(f"{header}\n{body}")

    comments_block = "\n\n".join(sections)

    return textwrap.dedent(f"""
        You are a YouTube analytics assistant helping a content creator understand
        their audience. Below are recent viewer comments grouped by video.

        Write a concise digest email body (no subject line needed) with these sections:

        ## Overall Sentiment
        One or two sentences on the general mood of the comments.

        ## What's Working
        Bullet list of specific things viewers praise, enjoy, or respond positively to.

        ## What to Improve
        Bullet list of concrete, actionable suggestions drawn from criticism or viewer requests.
        Focus on things the creator can actually change.

        ## Notable Comments
        Quote 2–3 standout comments (verbatim) with a one-line note on why each matters.

        ## Quick Stats
        - Videos reviewed: X
        - Total comments analyzed: X

        ---
        Tone: friendly and direct, as if briefing a colleague.
        Format: use markdown so headers and bullets render in email.

        COMMENTS:
        {comments_block}
    """).strip()


def analyze_with_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def markdown_to_html(md: str) -> str:
    """Lightweight markdown → HTML conversion (headers, bold, bullets, blockquotes)."""
    html = md
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"^> (.+)$", r"<blockquote>\1</blockquote>", html, flags=re.MULTILINE)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>\n?)+", lambda m: f"<ul>{m.group()}</ul>", html)
    paragraphs = []
    for block in re.split(r"\n{2,}", html):
        block = block.strip()
        if block and not block.startswith("<"):
            block = f"<p>{block}</p>"
        paragraphs.append(block)
    return "\n".join(paragraphs)


def send_email(subject: str, body_md: str) -> None:
    sender = os.environ["GMAIL_SENDER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("DIGEST_RECIPIENT", sender)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(markdown_to_html(body_md), "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"Digest sent to {recipient}.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ["YOUTUBE_API_KEY"]

    print("Resolving channel…")
    channel_id = resolve_channel_id(api_key)

    print(f"Fetching uploads playlist for channel {channel_id}…")
    uploads_playlist = get_uploads_playlist_id(api_key, channel_id)

    print(f"Fetching recent videos (last {DAYS_BACK} days, max {MAX_VIDEOS})…")
    videos = get_recent_videos(api_key, uploads_playlist)
    if not videos:
        print("No videos found on this channel.")
        return
    print(f"Found {len(videos)} video(s).")

    for video in videos:
        video["comments"] = get_comments(api_key, video["id"])
        print(f"  [{len(video['comments'])} comments] {video['title'][:70]}")

    total_comments = sum(len(v["comments"]) for v in videos)
    if total_comments == 0:
        print("No comments found. Digest not sent.")
        return

    print(f"\nAnalyzing {total_comments} comment(s) with Claude…")
    analysis = analyze_with_claude(build_prompt(videos))

    subject = f"YouTube Comment Digest — {datetime.now().strftime('%B %d, %Y')}"
    send_email(subject, analysis)


if __name__ == "__main__":
    main()
