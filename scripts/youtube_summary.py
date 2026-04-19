#!/usr/bin/env python3
"""
YouTube Comment Summary Routine

Fetches recent comments across your YouTube videos, uses Claude to analyze
sentiment and surface improvement opportunities, then emails you a report.

Usage:
    Copy .env.example to .env, fill in your values, then:
        pip install -r requirements.txt
        python youtube_summary.py

    Or set env vars directly and run without a .env file.
"""

import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "5"))
MAX_COMMENTS_PER_VIDEO = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))


def fetch_recent_videos(channel_id: str) -> list[dict]:
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "type": "video",
        "maxResults": MAX_VIDEOS,
    }
    response = httpx.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json().get("items", [])


def fetch_comments(video_id: str) -> list[dict]:
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "key": YOUTUBE_API_KEY,
        "videoId": video_id,
        "part": "snippet",
        "order": "relevance",
        "maxResults": MAX_COMMENTS_PER_VIDEO,
        "textFormat": "plainText",
    }
    response = httpx.get(url, params=params, timeout=15)
    if response.status_code == 403:
        return []
    response.raise_for_status()
    return response.json().get("items", [])


def analyze_with_claude(videos_with_comments: list[dict]) -> str:
    lines: list[str] = []
    for item in videos_with_comments:
        lines.append(f"\n=== {item['title']} ===")
        for c in item["comments"]:
            top = c["snippet"]["topLevelComment"]["snippet"]
            likes = top["likeCount"]
            text = top["textDisplay"]
            lines.append(f"[{likes} likes] {text}")

    comments_block = "\n".join(lines)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=(
            "You are an expert content strategist analyzing YouTube audience feedback. "
            "Be specific, honest, and actionable. Avoid generic advice."
        ),
        messages=[
            {
                "role": "user",
                "content": f"""Analyze the following YouTube comments and produce a structured report with these sections:

**Overall Sentiment**
One paragraph describing the general mood and tone of the audience.

**What Viewers Love**
Bullet list of 3–5 things viewers explicitly appreciate, with brief examples from the comments.

**Recurring Criticism**
Bullet list of the most common complaints or frustrations, with supporting quotes where relevant.

**Actionable Improvements**
Numbered list of specific things to change or try, ranked by how frequently they appear and their likely impact.

**Standout Comments**
2–3 notable comments worth reading verbatim (positive or negative). Quote them exactly.

Comments:
{comments_block}""",
            }
        ],
    )
    return message.content[0].text


def markdown_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"^(\d+)\. ", r"<li>", text, flags=re.MULTILINE)
    text = re.sub(r"^[-•] ", "<li>", text, flags=re.MULTILINE)
    text = text.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"<p>{text}</p>"


def build_email(analysis: str, video_count: int, comment_count: int) -> tuple[str, str]:
    date_str = datetime.now().strftime("%B %d, %Y")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: -apple-system, Arial, sans-serif;
      max-width: 680px;
      margin: 0 auto;
      color: #1a1a1a;
      background: #f4f4f4;
    }}
    .card {{
      background: white;
      border-radius: 10px;
      overflow: hidden;
      margin: 24px auto;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .header {{
      background: linear-gradient(135deg, #ff4500, #cc2200);
      color: white;
      padding: 28px 32px;
    }}
    .header h1 {{ margin: 0 0 4px; font-size: 22px; }}
    .header p  {{ margin: 0; opacity: 0.8; font-size: 13px; }}
    .stats {{
      display: flex;
      padding: 18px 32px;
      border-bottom: 1px solid #f0f0f0;
      background: #fafafa;
      gap: 40px;
    }}
    .stat .num   {{ font-size: 26px; font-weight: 700; color: #ff4500; }}
    .stat .label {{ font-size: 12px; color: #888; margin-top: 2px; }}
    .body {{
      padding: 28px 32px;
      line-height: 1.7;
      font-size: 15px;
    }}
    .body strong {{ color: #111; }}
    .footer {{
      padding: 16px 32px;
      font-size: 12px;
      color: #bbb;
      border-top: 1px solid #f0f0f0;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1>YouTube Comment Report</h1>
      <p>{date_str}</p>
    </div>
    <div class="stats">
      <div class="stat">
        <div class="num">{video_count}</div>
        <div class="label">Videos analyzed</div>
      </div>
      <div class="stat">
        <div class="num">{comment_count}</div>
        <div class="label">Comments reviewed</div>
      </div>
    </div>
    <div class="body">
      {markdown_to_html(analysis)}
    </div>
    <div class="footer">
      Generated automatically by youtube_summary.py
    </div>
  </div>
</body>
</html>"""

    plain = (
        f"YouTube Comment Report — {date_str}\n"
        f"Videos: {video_count}  |  Comments: {comment_count}\n"
        f"{'=' * 60}\n\n"
        f"{analysis}"
    )
    return html, plain


def send_email(subject: str, html_body: str, plain_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, GMAIL_APP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


def check_env() -> None:
    required = [
        "YOUTUBE_API_KEY",
        "YOUTUBE_CHANNEL_ID",
        "ANTHROPIC_API_KEY",
        "EMAIL_FROM",
        "EMAIL_TO",
        "GMAIL_APP_PASSWORD",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in your values."
        )


def main() -> None:
    check_env()

    print("Fetching recent videos...")
    videos = fetch_recent_videos(YOUTUBE_CHANNEL_ID)
    if not videos:
        print("No videos found for this channel ID.")
        return

    print(f"Found {len(videos)} video(s). Fetching comments...")
    videos_with_comments: list[dict] = []
    total_comments = 0

    for video in videos:
        video_id = video["id"]["videoId"]
        title = video["snippet"]["title"]
        comments = fetch_comments(video_id)
        if comments:
            videos_with_comments.append({"title": title, "comments": comments})
            total_comments += len(comments)
            print(f"  '{title[:55]}' — {len(comments)} comments")
        else:
            print(f"  '{title[:55]}' — comments disabled or none")

    if not videos_with_comments:
        print("No comments found. Exiting.")
        return

    print(f"\nAnalyzing {total_comments} comment(s) with Claude...")
    analysis = analyze_with_claude(videos_with_comments)

    print("Sending email...")
    html_body, plain_body = build_email(analysis, len(videos_with_comments), total_comments)
    subject = f"YouTube Comment Summary — {datetime.now().strftime('%B %d, %Y')}"
    send_email(subject, html_body, plain_body)

    print(f"Done! Report sent to {EMAIL_TO}")


if __name__ == "__main__":
    main()
