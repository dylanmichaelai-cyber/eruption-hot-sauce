#!/usr/bin/env python3
"""
Reads YouTube comment JSON, analyzes sentiment via Claude, sends email digest.
Usage: python3 analyze_and_email.py /path/to/comments.json
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_ADDRESS)


def build_prompt(data):
    video_summaries = []
    for v in data["videos"]:
        comments_text = "\n".join(
            f'  - [{c["likes"]} likes] {c["text"]}'
            for c in sorted(v["comments"], key=lambda x: -x["likes"])[:30]
        ) or "  (no comments)"
        video_summaries.append(
            f'Video: "{v["video_title"]}" ({v["url"]})\n'
            f'{v["comment_count"]} comments:\n{comments_text}'
        )

    return (
        f"You are analyzing YouTube comments for the Eruption Hot Sauce channel.\n"
        f"Period: last {data.get('days_back', 7)} days | Videos: {data['videos_found']} | "
        f"Total comments: {data['total_comments']}\n\n"
        + "\n\n---\n\n".join(video_summaries)
        + "\n\n"
        "Please analyze these comments and provide a structured digest with:\n\n"
        "1. **Overall Sentiment** — percentage positive/negative/neutral with a 1-2 sentence summary\n"
        "2. **What Viewers Love** — top 3-5 specific things people praise (with example quotes)\n"
        "3. **Criticism & Complaints** — top 3-5 pain points or negative feedback (with example quotes)\n"
        "4. **Improvement Opportunities** — concrete, actionable suggestions based on what viewers are asking for\n"
        "5. **Trending Topics** — recurring themes, questions, or requests across multiple videos\n"
        "6. **Standout Comments** — 2-3 particularly insightful or high-engagement comments worth reading\n\n"
        "Be specific and direct. Use exact quotes where helpful. Format for easy reading in an email."
    )


def analyze_comments(data):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": build_prompt(data)}],
    )
    return message.content[0].text


def build_html_email(analysis, data, date_str):
    analysis_html = (
        analysis
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n\n", "</p><p>")
        .replace("\n", "<br>")
        .replace("**", "<strong>", 1)
    )
    # Bold markdown (**text**)
    import re
    analysis_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", analysis)
    analysis_html = analysis_html.replace("\n\n", "</p><p>").replace("\n", "<br>")

    video_list = "".join(
        f'<li><a href="{v["url"]}">{v["video_title"]}</a> — {v["comment_count"]} comments</li>'
        for v in data["videos"]
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 680px; margin: 0 auto; padding: 24px; color: #1a1a1a; }}
  h1 {{ color: #c0392b; border-bottom: 3px solid #c0392b; padding-bottom: 8px; }}
  h2 {{ color: #2c3e50; margin-top: 28px; }}
  .meta {{ background: #f8f8f8; border-left: 4px solid #c0392b;
           padding: 12px 16px; border-radius: 0 4px 4px 0; margin-bottom: 24px; }}
  .analysis {{ line-height: 1.7; }}
  .analysis p {{ margin: 0 0 16px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 6px; }}
  a {{ color: #c0392b; }}
  .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #eee;
             font-size: 13px; color: #666; }}
</style>
</head>
<body>
  <h1>🌋 Eruption Hot Sauce — YouTube Digest</h1>
  <div class="meta">
    <strong>Week of {date_str}</strong> &nbsp;|&nbsp;
    {data['videos_found']} videos analyzed &nbsp;|&nbsp;
    {data['total_comments']} total comments
  </div>

  <h2>Videos Analyzed</h2>
  <ul>{video_list}</ul>

  <h2>AI Analysis</h2>
  <div class="analysis"><p>{analysis_html}</p></div>

  <div class="footer">
    Generated automatically by Claude · Eruption Hot Sauce YouTube Digest
  </div>
</body>
</html>
"""


def send_email(subject, html_body, text_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    print(f"Email sent to {RECIPIENT_EMAIL}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_and_email.py <comments.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    if "errors" in data:
        print(f"Errors in comment data: {data['errors']}")
        sys.exit(1)

    if data["total_comments"] == 0:
        print("No comments found — skipping email.")
        return

    print("Analyzing comments with Claude...")
    analysis = analyze_comments(data)

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject = f"Eruption Hot Sauce — YouTube Digest ({date_str})"
    html_body = build_html_email(analysis, data, date_str)

    print("Sending email...")
    send_email(subject, html_body, analysis)


if __name__ == "__main__":
    main()
