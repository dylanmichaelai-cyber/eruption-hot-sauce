#!/usr/bin/env python3
"""
Reads YouTube comment JSON from stdin (output of fetch_youtube_comments.py),
calls the Claude API to analyze sentiment and improvements, then sends a
summary email via Gmail SMTP.

Required environment variables:
  ANTHROPIC_API_KEY  – Claude API key
  GMAIL_ADDRESS      – sender address (also the recipient)
  GMAIL_APP_PASSWORD – Gmail App Password (not your main password)
                       Settings → Security → 2-Step Verification → App passwords
"""

import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

import urllib.request
import urllib.error


ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT          = os.environ.get("RECIPIENT_EMAIL", GMAIL_ADDRESS)


SYSTEM_PROMPT = """You are an expert YouTube channel strategist. You will receive
JSON data containing comments from a creator's recent videos. Analyse the comments
and return a single well-structured HTML email body (no <html>/<body> wrapper tags,
just the inner content). The email should include:

1. **Executive Summary** – 2-3 sentences on overall audience sentiment this week.
2. **Per-Video Breakdown** – for each video: a heading with the title and URL,
   a sentiment summary (positive/neutral/negative split as a rough %, in words),
   three bullet praise points, three bullet improvement suggestions, and the
   three most-liked comments (show the like count).
3. **Recurring Improvement Themes** – cross-video patterns grouped by theme
   (e.g. "Audio quality", "More tutorials", "Shorter intros").
4. **Keep Doing** – 3-5 things viewers consistently praise across videos.
5. A short footer: "Data covers the last 7 days · Eruption Hot Sauce channel".

Use clean inline styles so it renders well in Gmail (no external CSS).
Be specific and actionable — prioritise insights the creator can act on this week."""


def call_claude(comment_data: str) -> str:
    payload = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": comment_data}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"]


def send_email(html_body: str):
    subject = f"YouTube Comment Digest — {date.today().strftime('%B %d, %Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT, msg.as_string())

    print(f"Email sent to {RECIPIENT}")


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print("No input received on stdin.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(raw)
    if "error" in data:
        print(f"Upstream error: {data['error']}", file=sys.stderr)
        sys.exit(1)

    videos = data.get("videos", [])
    if not videos:
        print(data.get("message", "No videos to report."))
        return

    total_comments = sum(v["comment_count"] for v in videos)
    print(f"Analysing {len(videos)} video(s), {total_comments} comments…")

    html = call_claude(json.dumps(data, indent=2))
    send_email(html)


if __name__ == "__main__":
    main()
