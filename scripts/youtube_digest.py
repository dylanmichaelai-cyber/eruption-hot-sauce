"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel, analyzes sentiment
and improvement suggestions using Claude, then emails you a summary.

Usage:
    pip install -r requirements.txt
    cp .env.example .env  # fill in your values
    python youtube_digest.py
"""

import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_ADDRESS)
VIDEOS_TO_CHECK = int(os.environ.get("VIDEOS_TO_CHECK", "5"))
COMMENTS_PER_VIDEO = int(os.environ.get("COMMENTS_PER_VIDEO", "50"))


def fetch_recent_videos(youtube, channel_id: str, max_results: int) -> list[dict]:
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=max_results,
        order="date",
        type="video",
    )
    response = request.execute()
    return [
        {
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
        }
        for item in response.get("items", [])
    ]


def fetch_comments(youtube, video_id: str, max_results: int) -> list[dict]:
    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance",
            textFormat="plainText",
        )
        response = request.execute()
        return [
            {
                "author": item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
                "text": item["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
                "likes": item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
                "reply_count": item["snippet"]["totalReplyCount"],
            }
            for item in response.get("items", [])
        ]
    except Exception as e:
        print(f"  Warning: could not fetch comments for {video_id}: {e}")
        return []


def analyze_with_claude(client: anthropic.Anthropic, videos_with_comments: list[dict]) -> str:
    comment_text = ""
    for video in videos_with_comments:
        comment_text += f"\n## Video: {video['title']}\n"
        if not video["comments"]:
            comment_text += "  (no comments available)\n"
            continue
        for c in video["comments"]:
            comment_text += f"- [{c['likes']} likes] {c['text']}\n"

    prompt = f"""You are analyzing YouTube comments for a content creator. Review the comments below and provide a structured report covering:

1. **Overall Sentiment** — A brief paragraph describing how viewers feel overall (positive, mixed, negative).
2. **What People Love** — 3–5 bullet points on what viewers praise most.
3. **Criticism & Concerns** — 3–5 bullet points on the most common complaints or criticisms.
4. **Actionable Improvements** — 5 specific, prioritized suggestions the creator can act on right now to improve future videos (based purely on viewer feedback).
5. **Notable Comments** — 2–3 standout comments (positive or critical) worth reading.

Be honest and specific. Avoid vague advice. Reference actual comment themes.

---

{comment_text}
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_email_html(analysis: str, videos: list[dict]) -> tuple[str, str]:
    now = datetime.now(timezone.utc).strftime("%B %d, %Y")
    video_list_html = "".join(
        f'<li><a href="https://youtube.com/watch?v={v["video_id"]}">{v["title"]}</a></li>'
        for v in videos
    )

    # Convert markdown-ish analysis to simple HTML
    html_analysis = analysis.replace("\n\n", "</p><p>").replace("\n", "<br>")
    html_analysis = html_analysis.replace("**", "<strong>", 1)
    # Alternate bold open/close tags
    i = 0
    result = []
    for part in html_analysis.split("**"):
        result.append(part if i % 2 == 0 else f"<strong>{part}</strong>")
        i += 1
    html_analysis = "".join(result)

    subject = f"YouTube Comment Digest — {now}"

    html_body = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 24px; color: #222; }}
  h1 {{ color: #c00; font-size: 22px; }}
  h2 {{ color: #444; font-size: 16px; margin-top: 24px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 6px; }}
  .section {{ background: #f9f9f9; border-left: 4px solid #c00; padding: 12px 16px; margin: 16px 0; border-radius: 4px; }}
  .footer {{ font-size: 12px; color: #888; margin-top: 32px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
  <h1>YouTube Comment Digest</h1>
  <p><strong>Generated:</strong> {now}</p>

  <h2>Videos Analyzed</h2>
  <ul>{video_list_html}</ul>

  <h2>Analysis</h2>
  <div class="section">
    <p>{html_analysis}</p>
  </div>

  <div class="footer">
    Sent automatically by your YouTube Comment Digest routine.<br>
    Powered by YouTube Data API v3 + Claude.
  </div>
</body>
</html>"""

    return subject, html_body


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())


def main() -> None:
    print("Eruption Hot Sauce — YouTube Comment Digest")
    print("=" * 45)

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"Fetching last {VIDEOS_TO_CHECK} videos from channel {CHANNEL_ID}...")
    videos = fetch_recent_videos(youtube, CHANNEL_ID, VIDEOS_TO_CHECK)

    if not videos:
        print("No videos found. Check your CHANNEL_ID.")
        sys.exit(1)

    videos_with_comments = []
    for video in videos:
        print(f"  Fetching comments for: {video['title'][:60]}...")
        comments = fetch_comments(youtube, video["video_id"], COMMENTS_PER_VIDEO)
        print(f"    → {len(comments)} comments fetched")
        videos_with_comments.append({**video, "comments": comments})

    print("Analyzing comments with Claude...")
    analysis = analyze_with_claude(claude, videos_with_comments)

    print("Building email...")
    subject, html_body = build_email_html(analysis, videos)

    print(f"Sending email to {RECIPIENT_EMAIL}...")
    send_email(subject, html_body)

    print("Done! Check your inbox.")


if __name__ == "__main__":
    main()
