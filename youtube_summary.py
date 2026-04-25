#!/usr/bin/env python3
"""
YouTube Comment Analysis Routine

Fetches comments from all videos on your YouTube channel, analyzes audience
sentiment and improvement opportunities using Claude, then emails you a report.

Usage:
    python youtube_summary.py

Schedule with cron for weekly delivery, e.g. every Monday at 8am:
    0 8 * * 1 /usr/bin/python3 /path/to/youtube_summary.py
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "25"))
MAX_COMMENTS_PER_VIDEO = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "75"))


# ── YouTube helpers ────────────────────────────────────────────────────────────

def get_channel_videos(youtube, channel_id):
    """Return a list of {id, title} dicts for the channel's most recent videos."""
    videos = []
    next_page_token = None

    while len(videos) < MAX_VIDEOS:
        resp = youtube.search().list(
            part="id,snippet",
            channelId=channel_id,
            maxResults=min(50, MAX_VIDEOS - len(videos)),
            type="video",
            order="date",
            pageToken=next_page_token,
        ).execute()

        for item in resp.get("items", []):
            videos.append({
                "id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
            })

        next_page_token = resp.get("nextPageToken")
        if not next_page_token:
            break

    return videos


def get_video_comments(youtube, video_id):
    """Return a list of {text, likes} dicts for the top comments on a video."""
    comments = []
    next_page_token = None

    try:
        while len(comments) < MAX_COMMENTS_PER_VIDEO:
            resp = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, MAX_COMMENTS_PER_VIDEO - len(comments)),
                order="relevance",
                pageToken=next_page_token,
            ).execute()

            for item in resp.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                text = snippet.get("textDisplay", "").strip()
                if text:
                    comments.append({
                        "text": text,
                        "likes": snippet.get("likeCount", 0),
                    })

            next_page_token = resp.get("nextPageToken")
            if not next_page_token:
                break

    except HttpError as e:
        # Comments disabled or restricted on this video — skip silently
        if e.status_code not in (403, 400):
            raise

    return comments


def build_comment_corpus(videos_with_comments):
    """Flatten all video comments into a single structured text block."""
    parts = []
    total = 0

    for v in videos_with_comments:
        if not v["comments"]:
            continue
        lines = [f'### "{v["title"]}"']
        for c in v["comments"]:
            likes = f"  [{c['likes']} likes]" if c["likes"] > 0 else ""
            lines.append(f"- {c['text']}{likes}")
        parts.append("\n".join(lines))
        total += len(v["comments"])

    return "\n\n".join(parts), total


# ── Claude analysis ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert YouTube channel analyst with deep expertise in audience \
psychology and content strategy. Your reports are concise, specific, and \
directly actionable — never generic.

When given a set of viewer comments you will produce a report with exactly \
these five sections:

1. **Overall Sentiment** — percentage breakdown (positive / neutral / negative) \
and the 3-5 dominant emotional themes you detected.

2. **What Viewers Love** — the specific content elements, presentation choices, \
or topics that generate the most enthusiastic praise. Quote representative \
comments to back each point.

3. **Pain Points & Criticisms** — recurring complaints, confusions, or requests \
for change. Again, ground each point in actual comment language.

4. **Actionable Improvements** — 5-7 concrete changes ranked by potential \
impact. Each must be directly traceable to the comment evidence above.

5. **Emerging Opportunities** — topics, series ideas, or formats that viewers \
are explicitly asking for but the channel hasn't covered yet.

Write in a clear, professional tone suitable for a weekly email digest. \
Use markdown headers and bullet points throughout.\
"""


def analyze_with_claude(corpus_text, anthropic_client, video_count, total_comments):
    """Stream Claude's analysis of the comment corpus, with prompt caching."""
    print("\nAnalyzing with Claude (streaming)…")

    full_text = ""

    with anthropic_client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        # System prompt is stable across every run → cache it
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": (
                f"Below are viewer comments collected from {video_count} videos "
                f"on my YouTube channel ({total_comments} comments total). "
                "Please produce your full analysis report.\n\n"
                f"{corpus_text}"
            ),
        }],
    ) as stream:
        for chunk in stream.text_stream:
            print(chunk, end="", flush=True)
            full_text += chunk

        final = stream.get_final_message()
        usage = final.usage
        print(
            f"\n\n[Token usage — cached: {usage.cache_read_input_tokens} read / "
            f"{usage.cache_creation_input_tokens} written | "
            f"uncached: {usage.input_tokens} | output: {usage.output_tokens}]"
        )

    return full_text


# ── Email delivery ─────────────────────────────────────────────────────────────

def send_report_email(subject, body):
    """Send the report via Gmail SMTP using an App Password."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))

    print(f"\nSending report to {EMAIL_TO}…")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print("Email delivered successfully.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    required = {
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": YOUTUBE_CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM": EMAIL_FROM,
        "EMAIL_TO": EMAIL_TO,
        "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}")
        print("Copy .env.example → .env and fill in every value.")
        return

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 1. Collect videos
    print(f"Fetching up to {MAX_VIDEOS} videos from channel {YOUTUBE_CHANNEL_ID}…")
    videos = get_channel_videos(youtube, YOUTUBE_CHANNEL_ID)
    print(f"Found {len(videos)} videos.")

    # 2. Collect comments
    videos_with_comments = []
    for v in videos:
        print(f"  Comments ← \"{v['title'][:65]}\"…", end=" ", flush=True)
        comments = get_video_comments(youtube, v["id"])
        videos_with_comments.append({**v, "comments": comments})
        print(len(comments))

    # 3. Build corpus
    corpus, total_comments = build_comment_corpus(videos_with_comments)
    if total_comments == 0:
        print("No comments found. Comments may be disabled on all videos.")
        return

    print(f"\nCorpus: {total_comments} comments across {len(videos)} videos.")

    # 4. Analyse
    analysis = analyze_with_claude(corpus, anthropic_client, len(videos), total_comments)

    # 5. Email
    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"YouTube Sentiment Report — {date_str}"

    body = (
        f"YouTube Channel Comment Analysis\n"
        f"Generated: {date_str}\n"
        f"Channel ID: {YOUTUBE_CHANNEL_ID}\n"
        f"Videos analysed: {len(videos)}  |  Comments reviewed: {total_comments}\n"
        f"{'─' * 60}\n\n"
        f"{analysis}\n\n"
        f"{'─' * 60}\n"
        f"Sent automatically by youtube_summary.py\n"
    )

    send_report_email(subject, body)


if __name__ == "__main__":
    main()
