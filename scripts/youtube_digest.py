#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel, analyzes sentiment and
improvement opportunities with Claude, then emails you a summary.

Setup:
  1. Copy .env.example to .env and fill in your values
  2. pip install -r requirements.txt
  3. python youtube_digest.py

Schedule with cron (daily at 8am):
  0 8 * * * cd /path/to/scripts && python youtube_digest.py >> digest.log 2>&1
"""

import os
import smtplib
import textwrap
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

YOUTUBE_API_KEY      = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID           = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY    = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS        = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD   = os.environ["GMAIL_APP_PASSWORD"]
DIGEST_RECIPIENT     = os.environ["DIGEST_RECIPIENT"]
VIDEOS_TO_SCAN       = int(os.getenv("VIDEOS_TO_SCAN", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "100"))


# ── YouTube helpers ────────────────────────────────────────────────────────────

def get_youtube():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def fetch_recent_videos(youtube, channel_id: str, max_results: int) -> list[dict]:
    """Return the most recent uploads from the channel."""
    # Get the uploads playlist ID for the channel
    ch = youtube.channels().list(
        part="contentDetails,snippet",
        id=channel_id,
    ).execute()

    if not ch.get("items"):
        raise ValueError(f"Channel not found: {channel_id}")

    uploads_playlist = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_title    = ch["items"][0]["snippet"]["title"]

    items = youtube.playlistItems().list(
        part="snippet",
        playlistId=uploads_playlist,
        maxResults=max_results,
    ).execute().get("items", [])

    videos = []
    for item in items:
        snip = item["snippet"]
        videos.append({
            "id":        snip["resourceId"]["videoId"],
            "title":     snip["title"],
            "published": snip["publishedAt"],
            "url":       f"https://youtu.be/{snip['resourceId']['videoId']}",
        })

    return channel_title, videos


def fetch_comments(youtube, video_id: str, max_results: int) -> list[dict]:
    """Return top-level comments for a video (newest first)."""
    comments = []
    request = youtube.commentThreads().list(
        part="snippet",
        videoId=video_id,
        order="relevance",
        maxResults=min(max_results, 100),
        textFormat="plainText",
    )

    while request and len(comments) < max_results:
        response = request.execute()
        for item in response.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author":  top["authorDisplayName"],
                "text":    top["textDisplay"],
                "likes":   top["likeCount"],
                "replies": item["snippet"]["totalReplyCount"],
            })
        request = youtube.commentThreads().list_next(request, response)

    return comments[:max_results]


# ── Claude analysis ────────────────────────────────────────────────────────────

def build_comment_block(video: dict, comments: list[dict]) -> str:
    lines = [f'VIDEO: "{video["title"]}" ({video["url"]})']
    if not comments:
        lines.append("  (no comments)")
    for c in comments:
        likes = f" [{c['likes']} likes]" if c["likes"] else ""
        lines.append(f"  - {c['text']}{likes}")
    return "\n".join(lines)


def analyze_with_claude(channel_title: str, video_blocks: list[str]) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    all_comments = "\n\n".join(video_blocks)

    prompt = textwrap.dedent(f"""
        You are an expert YouTube growth strategist analyzing viewer comments for the channel "{channel_title}".

        Below are recent comments across the channel's latest videos.
        Your job is to produce a concise, actionable digest the creator can read in under 5 minutes.

        Structure your response exactly like this:

        ## Overall Sentiment
        One or two sentences describing the general mood of the audience right now.

        ## What's Landing Well
        Bullet list of specific things viewers love (themes, style, topics, presentation).
        Be concrete — quote or paraphrase real comments where useful.

        ## What Needs Work
        Bullet list of honest criticism, repeated complaints, or confusion points.
        No sugarcoating — the creator needs to hear this clearly.

        ## Top Improvement Actions
        Numbered list of 3–5 specific, prioritized changes the creator should make next.
        Each item: one sentence on WHAT to do, one sentence on WHY (backed by the comments).

        ## Standout Comments Worth Seeing
        3–5 individual comments that are especially insightful, funny, critical, or viral-worthy.
        Format: "Comment text" — @username

        ---
        COMMENTS:
        {all_comments}
    """).strip()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(subject: str, body_text: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = DIGEST_RECIPIENT

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, DIGEST_RECIPIENT, msg.as_string())


def markdown_to_html(md: str) -> str:
    """Minimal markdown → HTML for the email (no external deps needed)."""
    lines  = md.split("\n")
    output = []
    for line in lines:
        if line.startswith("## "):
            output.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            output.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("---"):
            output.append("<hr>")
        elif line.startswith("- "):
            output.append(f"<li>{line[2:]}</li>")
        elif line and line[0].isdigit() and ". " in line[:4]:
            dot = line.index(". ")
            output.append(f"<li><b>{line[:dot+1]}</b> {line[dot+2:]}</li>")
        elif line.strip() == "":
            output.append("<br>")
        else:
            output.append(f"<p>{line}</p>")

    html = "\n".join(output)
    return f"""
    <html><body style="font-family:sans-serif;max-width:700px;margin:auto;padding:24px;color:#222;">
    {html}
    <br><hr><p style="color:#888;font-size:12px;">
    Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by youtube_digest.py
    </p></body></html>
    """


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now().isoformat()}] Starting YouTube digest...")

    youtube = get_youtube()

    print(f"  Fetching last {VIDEOS_TO_SCAN} videos from channel {CHANNEL_ID}...")
    channel_title, videos = fetch_recent_videos(youtube, CHANNEL_ID, VIDEOS_TO_SCAN)
    print(f"  Channel: {channel_title} — {len(videos)} videos found")

    video_blocks = []
    total_comments = 0
    for video in videos:
        print(f"  Fetching comments for: {video['title']}")
        comments = fetch_comments(youtube, video["id"], MAX_COMMENTS_PER_VIDEO)
        total_comments += len(comments)
        video_blocks.append(build_comment_block(video, comments))
        print(f"    → {len(comments)} comments")

    print(f"  Analyzing {total_comments} comments with Claude...")
    analysis = analyze_with_claude(channel_title, video_blocks)

    date_str = datetime.now().strftime("%B %d, %Y")
    subject  = f"YouTube Digest — {channel_title} — {date_str}"

    print(f"  Sending digest email to {DIGEST_RECIPIENT}...")
    send_email(subject, analysis, markdown_to_html(analysis))

    print(f"  Done. Digest sent.")


if __name__ == "__main__":
    main()
