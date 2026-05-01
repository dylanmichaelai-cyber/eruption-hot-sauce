#!/usr/bin/env python3
"""
YouTube Comment Summary Routine

Fetches recent comments from your YouTube channel, analyzes them with Claude AI
for sentiment and improvement suggestions, then emails you a formatted summary.

Usage:
    python youtube_summary_routine.py

Schedule with cron (weekly on Mondays at 8am):
    0 8 * * 1 cd /path/to/eruption-hot-sauce && python youtube_summary_routine.py
"""

import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL") or os.environ["GMAIL_ADDRESS"]
DAYS_BACK = int(os.environ.get("DAYS_BACK", "7"))
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "100"))


def fetch_recent_videos(youtube, channel_id: str, days_back: int, max_results: int) -> list[dict]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    response = (
        youtube.search()
        .list(
            channelId=channel_id,
            part="id,snippet",
            type="video",
            publishedAfter=published_after,
            maxResults=max_results,
            order="date",
        )
        .execute()
    )

    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
        }
        for item in response.get("items", [])
    ]


def fetch_comments(youtube, video_id: str, max_results: int) -> list[dict]:
    comments = []
    try:
        request = youtube.commentThreads().list(
            videoId=video_id,
            part="snippet",
            maxResults=min(max_results, 100),
            order="relevance",
            textFormat="plainText",
        )
        while request and len(comments) < max_results:
            response = request.execute()
            for item in response.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append(
                    {
                        "text": top["textDisplay"],
                        "likes": top["likeCount"],
                        "author": top["authorDisplayName"],
                    }
                )
            request = youtube.commentThreads().list_next(request, response)
    except HttpError as e:
        if e.status_code == 403:
            print(f"  Skipping video {video_id}: comments are disabled.")
        else:
            print(f"  Warning: could not fetch comments for {video_id}: {e}")
    return comments[:max_results]


def analyze_comments(client: anthropic.Anthropic, videos_with_comments: list[dict]) -> str:
    sections = []
    for video in videos_with_comments:
        if not video["comments"]:
            continue
        comment_lines = "\n".join(
            f'- [{c["likes"]} likes] {c["text"][:300]}'
            for c in video["comments"][:60]
        )
        sections.append(f'### Video: "{video["title"]}"\n{comment_lines}')

    if not sections:
        return "No comments were found in the selected time window."

    prompt = f"""You are a YouTube content strategist. Analyze the following comments from a hot sauce YouTube channel's recent videos.

Provide a structured report covering:

1. **Overall Sentiment** — Concise breakdown (% positive / neutral / negative) with a 1-sentence mood summary.
2. **What Viewers Love** — Top 3–5 things viewers consistently praise (be specific, cite examples where possible).
3. **Actionable Improvements** — Top 3–5 specific, actionable things to improve based on viewer feedback.
4. **Trending Topics & Requests** — What topics, products, or formats are viewers asking for most?
5. **Standout Comments** — Quote 2–3 particularly insightful or representative comments (with attribution).

Base everything strictly on the comments provided. Be direct and practical.

---

{chr(10).join(sections)}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="You are a helpful YouTube content strategist who gives clear, actionable feedback.",
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_email(
    analysis: str, videos_with_comments: list[dict], days_back: int
) -> tuple[str, str, str]:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    total_comments = sum(len(v["comments"]) for v in videos_with_comments)
    active_videos = [v for v in videos_with_comments if v["comments"]]
    subject = f"YouTube Comment Summary — {today}"

    # Plain text
    video_lines = "\n".join(
        f'  • {v["title"]} ({len(v["comments"])} comments)' for v in active_videos
    )
    text_body = (
        f"YouTube Comment Summary — {today}\n"
        f"Last {days_back} days · {total_comments} comments · {len(active_videos)} video(s)\n\n"
        f"Videos analyzed:\n{video_lines}\n\n"
        f"{analysis}\n\n"
        "---\nGenerated by youtube_summary_routine.py"
    )

    # HTML — convert markdown bold (**text**) and headings (### text)
    analysis_html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", analysis)
    analysis_html = re.sub(
        r"^### (.+)$", r"<h3>\1</h3>", analysis_html, flags=re.MULTILINE
    )
    analysis_html = re.sub(
        r"^## (.+)$", r"<h2>\1</h2>", analysis_html, flags=re.MULTILINE
    )
    analysis_html = re.sub(
        r"^# (.+)$", r"<h1>\1</h1>", analysis_html, flags=re.MULTILINE
    )
    # Numbered / bullet lists
    analysis_html = re.sub(
        r"^(\d+)\. (.+)$", r"<li>\2</li>", analysis_html, flags=re.MULTILINE
    )
    analysis_html = re.sub(
        r"^[-•] (.+)$", r"<li>\1</li>", analysis_html, flags=re.MULTILINE
    )
    analysis_html = analysis_html.replace("\n\n", "</p><p>").replace("\n", "<br>")

    video_list_html = "".join(
        f'<li><strong>{v["title"]}</strong> &mdash; {len(v["comments"])} comment(s)</li>'
        for v in active_videos
    )

    html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: -apple-system, Arial, sans-serif;
    max-width: 680px;
    margin: 0 auto;
    padding: 24px;
    color: #222;
    line-height: 1.6;
  }}
  h1 {{ color: #cc2200; margin-bottom: 4px; }}
  h2 {{ color: #cc2200; margin-top: 28px; }}
  h3 {{ color: #444; margin-top: 20px; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  .analysis {{
    background: #fafafa;
    border-left: 4px solid #cc2200;
    padding: 20px 24px;
    border-radius: 4px;
    margin-top: 16px;
  }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 6px; }}
  footer {{ margin-top: 40px; color: #aaa; font-size: 12px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
  <h1>YouTube Comment Summary</h1>
  <p class="meta">
    {today} &nbsp;·&nbsp; Last {days_back} days &nbsp;·&nbsp;
    {total_comments} comment(s) across {len(active_videos)} video(s)
  </p>

  <h2>Videos Analyzed</h2>
  <ul>{video_list_html}</ul>

  <h2>Analysis</h2>
  <div class="analysis"><p>{analysis_html}</p></div>

  <footer>Generated automatically by youtube_summary_routine.py</footer>
</body>
</html>"""

    return subject, text_body, html_body


def send_email(subject: str, text_body: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())


def main() -> None:
    print("=" * 50)
    print("YouTube Comment Summary Routine")
    print("=" * 50)

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"\nFetching videos from the last {DAYS_BACK} days...")
    videos = fetch_recent_videos(youtube, YOUTUBE_CHANNEL_ID, DAYS_BACK, MAX_VIDEOS)

    if not videos:
        print("No recent videos found. Nothing to summarize.")
        return

    print(f"Found {len(videos)} video(s). Fetching comments...")
    videos_with_comments = []
    for video in videos:
        title_preview = video["title"][:55] + ("..." if len(video["title"]) > 55 else "")
        print(f"  → {title_preview}")
        comments = fetch_comments(youtube, video["id"], MAX_COMMENTS_PER_VIDEO)
        print(f"     {len(comments)} comment(s) fetched")
        videos_with_comments.append({**video, "comments": comments})

    total = sum(len(v["comments"]) for v in videos_with_comments)
    print(f"\nAnalyzing {total} comment(s) with Claude...")
    analysis = analyze_comments(client, videos_with_comments)

    print("Building email...")
    subject, text_body, html_body = build_email(analysis, videos_with_comments, DAYS_BACK)

    print(f"Sending summary to {RECIPIENT_EMAIL}...")
    send_email(subject, text_body, html_body)

    print("\nDone! Email sent successfully.")


if __name__ == "__main__":
    main()
