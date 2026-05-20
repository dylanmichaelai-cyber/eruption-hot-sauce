"""
YouTube Comment Sentiment Analyzer
Fetches recent comments from your YouTube channel, analyzes them with Claude,
and emails you a summary of audience sentiment and improvement suggestions.

Setup: copy .env.example to .env and fill in your credentials.
Run:   python3 youtube_comment_summary.py
Cron:  0 9 * * 1  cd /path/to/scripts && python3 youtube_comment_summary.py
"""

import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

YOUTUBE_API_KEY   = os.environ["YOUTUBE_API_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EMAIL_FROM        = os.environ["EMAIL_FROM"]
EMAIL_TO          = os.environ["EMAIL_TO"]
EMAIL_APP_PASSWORD = os.environ["EMAIL_APP_PASSWORD"]
SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.getenv("SMTP_PORT", "587"))

MAX_VIDEOS    = int(os.getenv("MAX_VIDEOS", "10"))
MAX_COMMENTS  = int(os.getenv("MAX_COMMENTS_PER_VIDEO", "50"))


def fetch_recent_videos(youtube, channel_id: str, max_results: int) -> list[dict]:
    response = youtube.search().list(
        part="id,snippet",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=max_results,
    ).execute()

    videos = []
    for item in response.get("items", []):
        videos.append({
            "id":    item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
        })
    return videos


def fetch_comments(youtube, video_id: str, max_results: int) -> list[str]:
    comments = []
    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_results, 100),
            order="relevance",
            textFormat="plainText",
        )
        while request and len(comments) < max_results:
            response = request.execute()
            for item in response.get("items", []):
                text = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                comments.append(text)
            request = youtube.commentThreads().list_next(request, response)
    except HttpError as e:
        if e.resp.status == 403:
            # Comments disabled on this video
            pass
        else:
            raise
    return comments[:max_results]


def analyze_with_claude(videos_with_comments: list[dict]) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    comment_dump = []
    for v in videos_with_comments:
        if not v["comments"]:
            continue
        comment_dump.append(f'### "{v["title"]}" ({v["published"][:10]})')
        for i, c in enumerate(v["comments"], 1):
            comment_dump.append(f'{i}. {c}')
        comment_dump.append("")

    if not comment_dump:
        return "No comments were found on your recent videos."

    comments_text = "\n".join(comment_dump)

    prompt = f"""You are an audience insights analyst. Below are recent YouTube comments across my latest videos.

{comments_text}

Please write a clear, actionable report with these sections:

## Overall Sentiment
A 2-3 sentence summary of how viewers generally feel. Include an approximate sentiment split (e.g. 70% positive, 20% neutral, 10% negative).

## What Viewers Love
Bullet points covering the specific things viewers praise most (topics, style, editing, personality, etc.).

## Common Criticisms & Pain Points
Bullet points covering recurring complaints or suggestions. Be specific — quote or paraphrase actual comments where helpful.

## Top Improvement Opportunities
A prioritized list (most impactful first) of concrete things I can change or add to my videos based on this feedback.

## Standout Comments
2-3 individual comments that are especially insightful, funny, or representative of the audience mood.

Keep the tone direct and honest. I want real feedback, not flattery."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_email(subject: str, body_html: str, body_text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def markdown_to_html(text: str) -> str:
    """Minimal markdown → HTML for the email body."""
    lines = text.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- ") or line.startswith("• "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")
    return "\n".join(html_lines)


def main() -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Starting YouTube comment analysis...")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    print(f"Fetching up to {MAX_VIDEOS} recent videos from channel {YOUTUBE_CHANNEL_ID}...")
    videos = fetch_recent_videos(youtube, YOUTUBE_CHANNEL_ID, MAX_VIDEOS)

    if not videos:
        print("No videos found. Check your YOUTUBE_CHANNEL_ID.")
        sys.exit(1)

    print(f"Found {len(videos)} videos. Fetching comments...")
    videos_with_comments = []
    for v in videos:
        comments = fetch_comments(youtube, v["id"], MAX_COMMENTS)
        print(f"  '{v['title']}' — {len(comments)} comments")
        videos_with_comments.append({**v, "comments": comments})

    total = sum(len(v["comments"]) for v in videos_with_comments)
    print(f"Analyzing {total} comments with Claude...")
    analysis = analyze_with_claude(videos_with_comments)

    now_str    = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject    = f"YouTube Audience Insights — {now_str}"
    html_body  = f"""
<html><body style="font-family:sans-serif;max-width:700px;margin:auto;padding:24px;color:#222;">
<h1 style="color:#c0392b;">YouTube Audience Insights</h1>
<p style="color:#666;font-size:0.9em;">Generated {now_str} · {total} comments across {len(videos)} videos</p>
<hr>
{markdown_to_html(analysis)}
<hr>
<p style="color:#aaa;font-size:0.8em;">Generated automatically by your YouTube Comment Analyzer.</p>
</body></html>"""
    text_body  = f"YouTube Audience Insights — {now_str}\n\n{analysis}"

    print(f"Sending email to {EMAIL_TO}...")
    send_email(subject, html_body, text_body)
    print("Done! Email sent successfully.")


if __name__ == "__main__":
    main()
