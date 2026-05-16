#!/usr/bin/env python3
"""
Eruption Hot Sauce — YouTube Comment Summary Routine
Fetches recent comments from your YouTube channel, analyzes sentiment and
improvement areas with Claude AI, then emails a digest to you.

Setup: see scripts/README.md
Run:  python3 scripts/youtube_summary.py
Cron: 0 9 * * 1 cd /path/to/eruption-hot-sauce && python3 scripts/youtube_summary.py
"""

import os
import sys
import smtplib
import html as html_lib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests anthropic")

try:
    import anthropic
except ImportError:
    sys.exit("Missing dependency: pip install anthropic")

# ── Config (set these as environment variables) ──────────────────────────────
YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID        = os.environ.get("YOUTUBE_CHANNEL_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_FROM        = os.environ.get("EMAIL_FROM", "")         # your Gmail address
EMAIL_PASSWORD    = os.environ.get("EMAIL_APP_PASSWORD", "") # Gmail App Password
EMAIL_TO          = os.environ.get("EMAIL_TO", EMAIL_FROM)   # defaults to self
MAX_VIDEOS        = int(os.environ.get("MAX_VIDEOS", "10"))
MAX_COMMENTS      = int(os.environ.get("MAX_COMMENTS", "100"))

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"


def check_config():
    missing = [k for k, v in {
        "YOUTUBE_API_KEY":   YOUTUBE_API_KEY,
        "YOUTUBE_CHANNEL_ID": CHANNEL_ID,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "EMAIL_FROM":        EMAIL_FROM,
        "EMAIL_APP_PASSWORD": EMAIL_PASSWORD,
    }.items() if not v]
    if missing:
        print("ERROR — missing environment variables:")
        for m in missing:
            print(f"  export {m}=...")
        print("\nSee scripts/README.md for setup instructions.")
        sys.exit(1)


def get_recent_videos():
    resp = requests.get(f"{YOUTUBE_BASE}/search", params={
        "part":       "snippet",
        "channelId":  CHANNEL_ID,
        "maxResults": MAX_VIDEOS,
        "order":      "date",
        "type":       "video",
        "key":        YOUTUBE_API_KEY,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json().get("items", [])


def get_comments(video_id):
    resp = requests.get(f"{YOUTUBE_BASE}/commentThreads", params={
        "part":       "snippet",
        "videoId":    video_id,
        "maxResults": MAX_COMMENTS,
        "order":      "relevance",
        "key":        YOUTUBE_API_KEY,
    }, timeout=15)
    if resp.status_code == 403:
        return []  # comments disabled on this video
    resp.raise_for_status()
    return [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in resp.json().get("items", [])
    ]


def build_prompt(videos_data):
    sections = []
    for v in videos_data:
        if not v["comments"]:
            continue
        lines = "\n".join(f"  • {c[:300]}" for c in v["comments"][:60])
        sections.append(f"### {v['title']}\n{lines}")

    if not sections:
        return None

    return f"""You are analyzing YouTube comments for Eruption Hot Sauce, a hot sauce brand.

Below are recent comments across their YouTube videos. Analyze them and produce a structured report.

{chr(10).join(sections)}

---

Write a concise, honest report with these sections:

**1. Overall Sentiment**
One paragraph on the general tone. Estimate % positive / neutral / negative.

**2. What Viewers Love**
Bullet list of the top 4–6 things viewers consistently praise.

**3. Criticisms & Pain Points**
Bullet list of the top 4–6 complaints or frustrations mentioned.

**4. Improvement Recommendations**
Bullet list of 4–6 specific, actionable things to improve in future videos (content, production, topics, etc.).

**5. Trending Questions / Themes**
Bullet list of recurring questions or topics viewers keep bringing up.

Keep each point short and direct. No fluff."""


def analyze(videos_data):
    prompt = build_prompt(videos_data)
    if not prompt:
        return "No comments were found across the analyzed videos."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def render_html(summary, videos_data, date_str):
    def md_to_html(text):
        lines = text.split("\n")
        out, in_list = [], False
        for line in lines:
            if line.startswith("**") and line.endswith("**"):
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append(f'<h3 class="section-title">{html_lib.escape(line.strip("*"))}</h3>')
            elif line.strip().startswith("•") or line.strip().startswith("-"):
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                out.append(f"<li>{html_lib.escape(line.strip().lstrip('•- '))}</li>")
            elif line.strip():
                if in_list:
                    out.append("</ul>")
                    in_list = False
                out.append(f"<p>{html_lib.escape(line)}</p>")
        if in_list:
            out.append("</ul>")
        return "\n".join(out)

    videos_rows = "".join(
        f'<tr><td>{html_lib.escape(v["title"])}</td>'
        f'<td style="text-align:right;color:#c0392b;">{v["comment_count"]}</td></tr>'
        for v in videos_data
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:#f4f4f4;margin:0;padding:24px;color:#1a1a1a}}
  .wrap{{max-width:660px;margin:0 auto;background:#fff;border-radius:12px;
         overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
  .hdr{{background:linear-gradient(135deg,#8b0000,#c0392b);padding:36px 32px;
        text-align:center}}
  .hdr h1{{color:#fff;margin:0;font-size:26px;letter-spacing:.02em}}
  .hdr p{{color:rgba(255,255,255,.75);margin:6px 0 0;font-size:14px}}
  .body{{padding:32px}}
  table{{width:100%;border-collapse:collapse;margin-bottom:28px;font-size:14px}}
  th{{background:#fafafa;text-align:left;padding:8px 10px;
      border-bottom:2px solid #eee;font-size:12px;
      text-transform:uppercase;letter-spacing:.06em;color:#666}}
  td{{padding:8px 10px;border-bottom:1px solid #f0f0f0}}
  h3.section-title{{color:#c0392b;font-size:15px;margin:24px 0 8px;
                    border-bottom:1px solid #f0e0e0;padding-bottom:6px}}
  ul{{margin:0 0 12px;padding-left:22px;line-height:1.9;font-size:14px}}
  p{{line-height:1.7;font-size:14px;margin:0 0 12px}}
  .foot{{text-align:center;padding:20px;font-size:12px;color:#aaa;
         border-top:1px solid #f0f0f0}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>Eruption Hot Sauce</h1>
    <p>YouTube Comment Summary &mdash; {date_str}</p>
  </div>
  <div class="body">
    <table>
      <thead><tr><th>Video</th><th style="text-align:right">Comments</th></tr></thead>
      <tbody>{videos_rows}</tbody>
    </table>
    {md_to_html(summary)}
  </div>
  <div class="foot">Generated automatically &middot; Eruption Hot Sauce Comment Tracker</div>
</div>
</body>
</html>"""


def send_email(summary, videos_data):
    date_str = datetime.now().strftime("%B %d, %Y")
    subject  = f"YouTube Comment Summary — {date_str}"

    plain_videos = "\n".join(
        f"  • {v['title']} ({v['comment_count']} comments)" for v in videos_data
    )
    plain = f"""{subject}

Videos analyzed:
{plain_videos}

{summary}

---
Generated by Eruption Hot Sauce Comment Tracker
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(render_html(summary, videos_data, date_str), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

    print(f"Email sent to {EMAIL_TO}")


def main():
    check_config()

    print("Fetching recent videos...")
    raw_videos = get_recent_videos()
    if not raw_videos:
        print("No videos found. Check your YOUTUBE_CHANNEL_ID.")
        sys.exit(1)

    videos_data = []
    for item in raw_videos:
        vid  = item["id"]["videoId"]
        title = item["snippet"]["title"]
        print(f"  Fetching comments: {title[:60]}")
        comments = get_comments(vid)
        videos_data.append({
            "title":         title,
            "video_id":      vid,
            "comments":      comments,
            "comment_count": len(comments),
        })

    total = sum(v["comment_count"] for v in videos_data)
    print(f"\nAnalyzing {total} comments across {len(videos_data)} videos with Claude...")

    summary = analyze(videos_data)

    print("\n" + "─" * 60)
    print(summary)
    print("─" * 60 + "\n")

    print("Sending email...")
    send_email(summary, videos_data)
    print("Done.")


if __name__ == "__main__":
    main()
