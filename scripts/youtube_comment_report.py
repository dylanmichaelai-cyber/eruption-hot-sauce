#!/usr/bin/env python3
"""
YouTube Comment Report Generator
Fetches recent comments from a YouTube channel, analyzes sentiment and themes,
and returns a structured report for emailing.

Usage:
  YOUTUBE_API_KEY=<key> YOUTUBE_CHANNEL_ID=<id> python3 youtube_comment_report.py

Environment variables:
  YOUTUBE_API_KEY       - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID    - Your YouTube channel ID (e.g. UCxxxxxxxxxxxxxxxxxx)
  MAX_VIDEOS            - Number of recent videos to scan (default: 5)
  MAX_COMMENTS_PER_VIDEO - Max comments per video (default: 50)
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from collections import Counter

API_BASE = "https://www.googleapis.com/youtube/v3"
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")
MAX_VIDEOS = int(os.environ.get("MAX_VIDEOS", "5"))
MAX_COMMENTS = int(os.environ.get("MAX_COMMENTS_PER_VIDEO", "50"))


def yt_get(endpoint, params):
    params["key"] = API_KEY
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def get_recent_videos():
    data = yt_get("search", {
        "part": "snippet",
        "channelId": CHANNEL_ID,
        "type": "video",
        "order": "date",
        "maxResults": MAX_VIDEOS,
    })
    return [
        {
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published": item["snippet"]["publishedAt"],
        }
        for item in data.get("items", [])
    ]


def get_comments(video_id):
    try:
        data = yt_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": MAX_COMMENTS,
            "order": "relevance",
            "textFormat": "plainText",
        })
        comments = []
        for item in data.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "text": top["textDisplay"],
                "likes": top["likeCount"],
                "author": top["authorDisplayName"],
            })
        return comments
    except Exception as e:
        return []


POSITIVE_WORDS = {
    "love", "great", "amazing", "awesome", "excellent", "fantastic", "perfect",
    "helpful", "good", "best", "thanks", "thank", "incredible", "brilliant",
    "outstanding", "superb", "wonderful", "nice", "useful", "informative",
    "clear", "easy", "simple", "fun", "enjoy", "enjoyed", "learned",
}
NEGATIVE_WORDS = {
    "bad", "terrible", "awful", "worst", "hate", "boring", "confusing",
    "difficult", "hard", "unclear", "wrong", "broken", "slow", "poor",
    "disappointing", "useless", "complicated", "doesn't work", "not working",
    "problem", "issue", "error", "fix", "help", "question", "why",
}
IMPROVEMENT_WORDS = {
    "more", "please", "could", "should", "would", "wish", "hope", "want",
    "need", "suggest", "suggestion", "improve", "better", "next", "part",
    "add", "missing", "include", "explain", "tutorial", "example",
}


def classify_sentiment(text):
    lower = text.lower()
    words = set(lower.split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"


def extract_themes(comments):
    theme_keywords = {
        "requests for more content": ["more", "part 2", "next", "series", "follow up"],
        "praise for clarity": ["clear", "simple", "easy", "understand", "explained"],
        "requests for deeper detail": ["detail", "deeper", "advanced", "more depth", "explain"],
        "questions / confusion": ["how", "why", "what", "confused", "help", "question"],
        "technical issues": ["error", "doesn't work", "not working", "broken", "issue", "problem"],
        "topic requests": ["cover", "video about", "do a video", "make a video", "tutorial on"],
    }
    found = Counter()
    examples = {}
    for c in comments:
        lower = c["text"].lower()
        for theme, kws in theme_keywords.items():
            if any(kw in lower for kw in kws):
                found[theme] += 1
                if theme not in examples:
                    examples[theme] = c["text"][:120]
    return found, examples


def build_report(videos_data):
    all_comments = []
    video_summaries = []

    for video in videos_data:
        comments = video["comments"]
        all_comments.extend(comments)
        sentiments = [classify_sentiment(c["text"]) for c in comments]
        pos = sentiments.count("positive")
        neg = sentiments.count("negative")
        neu = sentiments.count("neutral")
        video_summaries.append({
            "title": video["title"],
            "comment_count": len(comments),
            "positive": pos,
            "negative": neg,
            "neutral": neu,
            "top_liked": max(comments, key=lambda c: c["likes"])["text"][:120] if comments else "",
        })

    total = len(all_comments)
    if total == 0:
        return None

    all_sentiments = [classify_sentiment(c["text"]) for c in all_comments]
    overall_pos = all_sentiments.count("positive") / total * 100
    overall_neg = all_sentiments.count("negative") / total * 100
    overall_neu = all_sentiments.count("neutral") / total * 100

    themes, examples = extract_themes(all_comments)

    improvements = []
    if themes["requests for more content"]:
        improvements.append(f"Viewers are asking for follow-up content ({themes['requests for more content']} mentions) — consider a Part 2 or series format.")
    if themes["questions / confusion"]:
        improvements.append(f"There are {themes['questions / confusion']} comments with questions or confusion — add a FAQ section or clarify key steps earlier in videos.")
    if themes["requests for deeper detail"]:
        improvements.append(f"{themes['requests for deeper detail']} viewers want more depth — consider longer deep-dives on popular topics.")
    if themes["technical issues"]:
        improvements.append(f"{themes['technical issues']} comments mention technical issues — consider adding a troubleshooting section or pinned comment with fixes.")
    if themes["topic requests"]:
        improvements.append(f"Viewers are requesting specific topics ({themes['topic requests']} mentions) — mine the comments for video ideas.")
    if overall_neg > 15:
        improvements.append(f"Negative sentiment is elevated at {overall_neg:.0f}% — review the most-disliked comments to identify recurring pain points.")
    if not improvements:
        improvements.append("Overall sentiment is strong. Keep the current format and consistency.")

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total_comments_analyzed": total,
        "overall_sentiment": {
            "positive_pct": round(overall_pos, 1),
            "negative_pct": round(overall_neg, 1),
            "neutral_pct": round(overall_neu, 1),
        },
        "top_themes": dict(themes.most_common(5)),
        "theme_examples": examples,
        "improvements": improvements,
        "video_summaries": video_summaries,
    }


def format_html_email(report):
    pos = report["overall_sentiment"]["positive_pct"]
    neg = report["overall_sentiment"]["negative_pct"]
    neu = report["overall_sentiment"]["neutral_pct"]

    videos_html = ""
    for v in report["video_summaries"]:
        top_liked_html = f'<p style="color:#555;font-style:italic;margin:4px 0 0">Top liked: "{v["top_liked"]}..."</p>' if v["top_liked"] else ""
        videos_html += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee"><strong>{v["title"]}</strong>
            {top_liked_html}
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{v["comment_count"]}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:#22863a">{v["positive"]}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:#cb2431">{v["negative"]}</td>
        </tr>"""

    improvements_html = "".join(f"<li style='margin:6px 0'>{i}</li>" for i in report["improvements"])

    themes_html = ""
    for theme, count in report["top_themes"].items():
        example = report["theme_examples"].get(theme, "")
        example_html = f'<br><span style="color:#555;font-size:12px;font-style:italic">e.g. "{example}..."</span>' if example else ""
        themes_html += f"<li style='margin:6px 0'><strong>{theme.title()}</strong> ({count} mentions){example_html}</li>"

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#333">
      <div style="background:#c0392b;color:white;padding:24px;border-radius:8px 8px 0 0">
        <h1 style="margin:0;font-size:22px">YouTube Comment Report</h1>
        <p style="margin:4px 0 0;opacity:0.85;font-size:14px">Generated {report["generated_at"]} &nbsp;·&nbsp; {report["total_comments_analyzed"]} comments analyzed</p>
      </div>

      <div style="padding:24px;background:#fff;border:1px solid #eee;border-top:none">

        <h2 style="margin-top:0;font-size:16px;color:#c0392b">Overall Sentiment</h2>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px">
          <div style="flex:1;min-width:120px;background:#f0fff4;border:1px solid #cce5cc;border-radius:6px;padding:12px;text-align:center">
            <div style="font-size:28px;font-weight:bold;color:#22863a">{pos}%</div>
            <div style="font-size:13px;color:#555">Positive</div>
          </div>
          <div style="flex:1;min-width:120px;background:#fff0f0;border:1px solid #f5c6c6;border-radius:6px;padding:12px;text-align:center">
            <div style="font-size:28px;font-weight:bold;color:#cb2431">{neg}%</div>
            <div style="font-size:13px;color:#555">Negative</div>
          </div>
          <div style="flex:1;min-width:120px;background:#f8f8f8;border:1px solid #ddd;border-radius:6px;padding:12px;text-align:center">
            <div style="font-size:28px;font-weight:bold;color:#555">{neu}%</div>
            <div style="font-size:13px;color:#555">Neutral</div>
          </div>
        </div>

        <h2 style="font-size:16px;color:#c0392b">Suggestions for Improvement</h2>
        <ul style="padding-left:20px;line-height:1.7">{improvements_html}</ul>

        <h2 style="font-size:16px;color:#c0392b">Top Comment Themes</h2>
        <ul style="padding-left:20px;line-height:1.7">{themes_html}</ul>

        <h2 style="font-size:16px;color:#c0392b">Per-Video Breakdown</h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead>
            <tr style="background:#f5f5f5">
              <th style="padding:8px;text-align:left;border-bottom:2px solid #ddd">Video</th>
              <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd">Comments</th>
              <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;color:#22863a">Positive</th>
              <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;color:#cb2431">Negative</th>
            </tr>
          </thead>
          <tbody>{videos_html}</tbody>
        </table>

      </div>
      <div style="padding:12px 24px;background:#f8f8f8;border:1px solid #eee;border-top:none;border-radius:0 0 8px 8px;font-size:12px;color:#999;text-align:center">
        Automated YouTube Comment Report · Eruption Hot Sauce Channel
      </div>
    </div>
    """


def main():
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    if not CHANNEL_ID:
        print("ERROR: YOUTUBE_CHANNEL_ID environment variable not set", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching {MAX_VIDEOS} most recent videos from channel {CHANNEL_ID}...")
    videos = get_recent_videos()
    if not videos:
        print("No videos found for this channel.")
        sys.exit(0)

    for v in videos:
        print(f"  Fetching comments for: {v['title']}")
        v["comments"] = get_comments(v["id"])
        print(f"    Got {len(v['comments'])} comments")

    report = build_report(videos)
    if not report:
        print("No comments found across any videos.")
        sys.exit(0)

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
