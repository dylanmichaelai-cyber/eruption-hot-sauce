#!/usr/bin/env python3
"""
YouTube Comment Digest
Fetches recent comments from your YouTube channel videos and emails a summary
of viewer sentiment and improvement suggestions.

Required env vars:
  YOUTUBE_API_KEY      — YouTube Data API v3 key (Google Cloud Console)
  YOUTUBE_CHANNEL_ID   — Your channel ID (e.g. UCxxxxxxxxxxxxxxxx)
                         Find it at youtube.com/account_advanced
  EMAIL_TO             — Recipient email address
  GMAIL_USER           — Your Gmail address used to send
  GMAIL_APP_PASSWORD   — Gmail App Password (myaccount.google.com/apppasswords)

Optional:
  ANTHROPIC_API_KEY    — Enables Claude-powered analysis (recommended)
  MAX_VIDEOS           — How many recent videos to analyze (default: 5)
  MAX_COMMENTS         — Max comments per video (default: 100)
"""

import os
import re
import smtplib
import sys
from collections import Counter
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

# ── Config ────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "5"))
MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS", "100"))

YOUTUBE_BASE = "https://www.googleapis.com/youtube/v3"

# ── YouTube API ────────────────────────────────────────────────────────────────

def yt_get(endpoint, params):
    params["key"] = YOUTUBE_API_KEY
    resp = requests.get(f"{YOUTUBE_BASE}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_recent_videos():
    data = yt_get("search", {
        "channelId": YOUTUBE_CHANNEL_ID,
        "part": "snippet",
        "order": "date",
        "maxResults": MAX_VIDEOS,
        "type": "video",
    })
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"][:10],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id):
    try:
        data = yt_get("commentThreads", {
            "videoId": video_id,
            "part": "snippet",
            "maxResults": MAX_COMMENTS,
            "order": "relevance",
        })
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return []  # comments disabled on this video
        raise
    return [
        {
            "text": item["snippet"]["topLevelComment"]["snippet"]["textDisplay"],
            "likes": item["snippet"]["topLevelComment"]["snippet"]["likeCount"],
            "author": item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"],
        }
        for item in data.get("items", [])
    ]

# ── Sentiment analysis ─────────────────────────────────────────────────────────

POSITIVE_WORDS = {
    "love", "amazing", "great", "best", "incredible", "fantastic", "awesome",
    "delicious", "perfect", "excellent", "wonderful", "brilliant", "superb",
    "fire", "obsessed", "favorite", "favourite", "outstanding", "phenomenal",
    "hot", "spicy", "addicted", "addictive", "recommend", "worth", "buy",
}

NEGATIVE_WORDS = {
    "bad", "worst", "terrible", "awful", "horrible", "disgusting", "gross",
    "overpriced", "expensive", "bland", "mild", "weak", "disappointed",
    "disappointing", "hate", "never", "waste", "regret", "salty", "bitter",
}

IMPROVEMENT_WORDS = {
    "should", "could", "wish", "hope", "suggest", "suggestion", "try",
    "improve", "better", "next time", "please", "would be nice", "need",
    "needs", "want", "waiting", "when", "more", "less",
}


def basic_sentiment_analysis(videos_with_comments):
    """Keyword-based sentiment + theme extraction (no external API needed)."""
    all_comments = []
    for v in videos_with_comments:
        all_comments.extend(v["comments"])

    if not all_comments:
        return None

    pos = neg = neutral = 0
    improvement_comments = []
    word_freq: Counter = Counter()
    top_liked = sorted(all_comments, key=lambda c: c["likes"], reverse=True)[:5]

    stop_words = {
        "the", "a", "an", "is", "it", "this", "that", "and", "or", "but",
        "in", "on", "at", "to", "for", "of", "with", "my", "your", "their",
        "are", "was", "were", "be", "been", "have", "has", "had", "do",
        "does", "did", "will", "would", "could", "should", "i", "you", "we",
        "they", "he", "she", "so", "just", "its", "it's", "im", "i'm",
        "not", "no", "can", "get", "got", "like", "really", "very",
    }

    for comment in all_comments:
        text_lower = comment["text"].lower()
        words = re.findall(r"\b[a-z]{3,}\b", text_lower)
        for w in words:
            if w not in stop_words:
                word_freq[w] += 1

        p_hits = sum(1 for w in words if w in POSITIVE_WORDS)
        n_hits = sum(1 for w in words if w in NEGATIVE_WORDS)
        imp_hits = any(phrase in text_lower for phrase in IMPROVEMENT_WORDS)

        if p_hits > n_hits:
            pos += 1
        elif n_hits > p_hits:
            neg += 1
        else:
            neutral += 1

        if imp_hits:
            improvement_comments.append(comment)

    total = len(all_comments)
    pct_pos = round(pos / total * 100)
    pct_neg = round(neg / total * 100)
    pct_neu = round(neutral / total * 100)

    top_words = [w for w, _ in word_freq.most_common(30)
                 if w not in POSITIVE_WORDS | NEGATIVE_WORDS | IMPROVEMENT_WORDS][:12]

    return {
        "total": total,
        "pct_pos": pct_pos,
        "pct_neg": pct_neg,
        "pct_neu": pct_neu,
        "top_words": top_words,
        "improvement_comments": improvement_comments[:8],
        "top_liked": top_liked,
    }


def claude_analysis(videos_with_comments):
    """Full AI-powered analysis via Claude."""
    chunks = []
    for v in videos_with_comments:
        chunks.append(f"\n### {v['title']} (published {v['published']})")
        for c in v["comments"][:40]:
            line = f"  [{c['likes']} likes] {c['text'][:300]}"
            chunks.append(line)
    comments_block = "\n".join(chunks)

    prompt = f"""You are an expert YouTube channel analyst. Analyze these comments from a hot sauce channel and return a structured report covering:

1. **Overall Sentiment** — positive/neutral/negative breakdown with percentages.
2. **What Viewers Love** — 3-5 specific praised aspects (flavor, heat, packaging, storytelling, etc.).
3. **Top Themes** — recurring topics viewers mention.
4. **Improvement Opportunities** — 4-6 concrete, actionable suggestions drawn directly from viewer feedback.
5. **Standout Comments** — 3 memorable comments worth reading (quote them).
6. **One-line Growth Tip** — a single strategic suggestion for the channel.

Be specific, direct, and actionable. Avoid fluff.

COMMENTS:
{comments_block}"""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]

# ── Email builders ─────────────────────────────────────────────────────────────

def build_email_from_basic(stats, videos_with_comments):
    date_str = datetime.now().strftime("%B %d, %Y")
    total = stats["total"]
    video_rows_plain = "\n".join(
        f"  • {v['title']} ({len(v['comments'])} comments)"
        for v in videos_with_comments
    )
    imp_rows_plain = "\n".join(
        f"  [{c['likes']} likes] \"{c['text'][:200]}\""
        for c in stats["improvement_comments"]
    ) or "  (none found)"
    top_liked_plain = "\n".join(
        f"  [{c['likes']} likes] \"{c['text'][:200]}\""
        for c in stats["top_liked"]
    )
    themes = ", ".join(stats["top_words"]) or "N/A"

    plain = f"""YouTube Comment Digest — {date_str}
{"=" * 50}

VIDEOS ANALYZED
{video_rows_plain}

SENTIMENT ({total} comments)
  Positive : {stats['pct_pos']}%
  Neutral  : {stats['pct_neu']}%
  Negative : {stats['pct_neg']}%

TOP THEMES
  {themes}

IMPROVEMENT SUGGESTIONS (comments mentioning feedback)
{imp_rows_plain}

MOST-LIKED COMMENTS
{top_liked_plain}

---
Tip: Add ANTHROPIC_API_KEY to your environment for deeper AI-powered analysis.
"""

    video_li = "".join(
        f"<li>{v['title']} <span style='color:#888'>({len(v['comments'])} comments)</span></li>"
        for v in videos_with_comments
    )
    imp_li = "".join(
        f"<li><em>\"{c['text'][:250]}\"</em> <span style='color:#e63c2f'>👍 {c['likes']}</span></li>"
        for c in stats["improvement_comments"]
    ) or "<li>None detected</li>"
    top_li = "".join(
        f"<li><em>\"{c['text'][:250]}\"</em> <span style='color:#e63c2f'>👍 {c['likes']}</span></li>"
        for c in stats["top_liked"]
    )

    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:660px;margin:0 auto;padding:24px;color:#222">
<h1 style="color:#e63c2f;margin-bottom:4px">🌶️ YouTube Comment Digest</h1>
<p style="color:#888;margin-top:0">{date_str}</p>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Videos Analyzed</h2>
<ul>{video_li}</ul>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Sentiment — {total} comments</h2>
<table style="border-collapse:collapse;width:100%;max-width:320px">
  <tr><td style="padding:6px 12px;background:#e8f5e9;border-radius:4px">Positive</td>
      <td style="padding:6px 16px;font-weight:bold;color:#2e7d32">{stats['pct_pos']}%</td></tr>
  <tr><td style="padding:6px 12px;background:#f5f5f5;border-radius:4px">Neutral</td>
      <td style="padding:6px 16px;font-weight:bold;color:#555">{stats['pct_neu']}%</td></tr>
  <tr><td style="padding:6px 12px;background:#ffebee;border-radius:4px">Negative</td>
      <td style="padding:6px 16px;font-weight:bold;color:#c62828">{stats['pct_neg']}%</td></tr>
</table>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Top Themes</h2>
<p>{themes}</p>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Improvement Opportunities</h2>
<ul>{imp_li}</ul>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Most-Liked Comments</h2>
<ul>{top_li}</ul>

<hr style="margin-top:32px">
<p style="color:#aaa;font-size:12px">
  💡 Tip: Set <code>ANTHROPIC_API_KEY</code> in your environment for richer AI-powered analysis.<br>
  Generated by the Eruption Hot Sauce YouTube Digest routine.
</p>
</body></html>"""

    return f"YouTube Comment Digest — {date_str}", plain, html


def build_email_from_claude(analysis_text, videos_with_comments):
    date_str = datetime.now().strftime("%B %d, %Y")
    total_comments = sum(len(v["comments"]) for v in videos_with_comments)
    video_li = "".join(
        f"<li>{v['title']} <span style='color:#888'>({len(v['comments'])} comments)</span></li>"
        for v in videos_with_comments
    )
    analysis_html = (
        analysis_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:660px;margin:0 auto;padding:24px;color:#222">
<h1 style="color:#e63c2f;margin-bottom:4px">🌶️ YouTube Comment Digest</h1>
<p style="color:#888;margin-top:0">{date_str} &nbsp;·&nbsp; {total_comments} comments analyzed across {len(videos_with_comments)} videos</p>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Videos</h2>
<ul>{video_li}</ul>

<h2 style="border-bottom:2px solid #e63c2f;padding-bottom:6px">Analysis</h2>
<div style="background:#fafafa;border-left:4px solid #e63c2f;padding:16px;border-radius:4px;line-height:1.7">
{analysis_html}
</div>

<hr style="margin-top:32px">
<p style="color:#aaa;font-size:12px">Powered by Claude · Eruption Hot Sauce YouTube Digest</p>
</body></html>"""

    plain = f"YouTube Comment Digest — {date_str}\n\n{analysis_text}"
    return f"YouTube Comment Digest — {date_str}", plain, html

# ── Email sending ──────────────────────────────────────────────────────────────

def send_email(subject, plain, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())

# ── Main ───────────────────────────────────────────────────────────────────────

def validate_config():
    missing = []
    for var in ("YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID", "EMAIL_TO",
                "GMAIL_USER", "GMAIL_APP_PASSWORD"):
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print("ERROR: Missing required environment variables:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)


def main():
    validate_config()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] YouTube Comment Digest starting...")

    print(f"  Fetching recent {MAX_VIDEOS} videos for channel {YOUTUBE_CHANNEL_ID}...")
    videos = get_recent_videos()
    if not videos:
        print("  No videos found — exiting.")
        sys.exit(0)

    videos_with_comments = []
    for v in videos:
        print(f"  Fetching comments: {v['title'][:60]}")
        comments = get_comments(v["id"])
        videos_with_comments.append({**v, "comments": comments})
        print(f"    → {len(comments)} comments")

    if ANTHROPIC_API_KEY:
        print("  Running Claude analysis...")
        analysis = claude_analysis(videos_with_comments)
        subject, plain, html = build_email_from_claude(analysis, videos_with_comments)
    else:
        print("  Running keyword sentiment analysis (set ANTHROPIC_API_KEY for AI analysis)...")
        stats = basic_sentiment_analysis(videos_with_comments)
        if not stats:
            print("  No comments found to analyze.")
            sys.exit(0)
        subject, plain, html = build_email_from_basic(stats, videos_with_comments)

    print(f"  Sending digest to {EMAIL_TO}...")
    send_email(subject, plain, html)
    print("  Done! ✓")


if __name__ == "__main__":
    main()
