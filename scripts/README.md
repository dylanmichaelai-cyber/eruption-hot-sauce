# YouTube Comment Summary — Setup Guide

## What it does
Fetches the latest comments from your YouTube channel, runs them through
Claude AI for sentiment analysis and improvement suggestions, then emails
you a formatted digest.

---

## 1. Install dependencies

```bash
pip install requests anthropic
```

---

## 2. Get a server-side YouTube API key

Your current API key has **HTTP referrer restrictions** (browser-only).
You need one that works from a server:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **API Key**
3. Under *Key restrictions*, select **None** (or *IP addresses* if you want to lock it down)
4. Enable the **YouTube Data API v3** if not already enabled

---

## 3. Find your YouTube Channel ID

1. Go to your YouTube channel page
2. Click your profile picture → **Your channel**
3. The URL will look like: `youtube.com/channel/UCxxxxxxxxxxxxxxxxxx`
4. Copy the `UCxxx...` part — that's your Channel ID

Alternatively: Studio → Settings → Channel → Advanced settings → Channel ID

---

## 4. Get an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com) and create an API key.

---

## 5. Set up Gmail sending

1. Go to your Google Account → **Security** → **2-Step Verification** (must be on)
2. Search for **App passwords** → Create one for "Mail"
3. Use that 16-character password as `EMAIL_APP_PASSWORD`

---

## 6. Set environment variables

```bash
export YOUTUBE_API_KEY="YOUR_SERVER_API_KEY"
export YOUTUBE_CHANNEL_ID="UCxxxxxxxxxxxxxxxxxx"
export ANTHROPIC_API_KEY="sk-ant-..."
export EMAIL_FROM="dylanmichaelai@gmail.com"
export EMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export EMAIL_TO="dylanmichaelai@gmail.com"   # optional, defaults to EMAIL_FROM
export MAX_VIDEOS=10                          # optional, how many recent videos to check
export MAX_COMMENTS=100                       # optional, comments per video
```

---

## 7. Run it

```bash
python3 scripts/youtube_summary.py
```

---

## 8. Schedule it (weekly on Monday at 9am)

```bash
crontab -e
```

Add this line:
```
0 9 * * 1 cd /path/to/eruption-hot-sauce && python3 scripts/youtube_summary.py >> /tmp/yt_summary.log 2>&1
```

Or use a `.env` file with your variables and source it first:
```
0 9 * * 1 cd /path/to/eruption-hot-sauce && source .env && python3 scripts/youtube_summary.py
```
