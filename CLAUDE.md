# Eruption Hot Sauce — Claude Code Context

## Project
Static landing page for ERUPTION hot sauce. Pure HTML/CSS/JS, deployed on Vercel.
No build step needed. Frames in `/frames/` drive the scroll-animated volcano sequence.

---

## YouTube Comments Summary Routine

**Purpose:** Fetch recent YouTube video comments, analyze viewer sentiment and feedback,
and email a summary report to d.mcderm80@gmail.com.

**Schedule:** Run daily or weekly via claude.ai/code/routines.

**Required Cloud Environment variables:**
- `YOUTUBE_API_KEY` — YouTube Data API v3 key (restricted to YouTube Data API)
- `YOUTUBE_CHANNEL_ID` — your YouTube channel ID (e.g. `UCxxxxxxxxxxxxxxxx`)
  OR `YOUTUBE_CHANNEL_HANDLE` — your channel handle without @ (e.g. `eruption`)

**Network Access:** Set to Full in Cloud Environment settings.

**Connectors:** Gmail must be connected at claude.ai/settings → Connectors.

### Routine Prompt

```
Run the script at scripts/youtube_summary.py using the YOUTUBE_API_KEY and YOUTUBE_CHANNEL_ID
environment variables. The script will output a JSON report of recent video comments.

Once you have the JSON output, analyze it and produce a summary covering:
1. Overall sentiment across all videos (positive / neutral / negative breakdown)
2. Top 3 things viewers love (with example quotes)
3. Top 3 improvement suggestions mentioned most often (with example quotes)
4. Any recurring questions or requests from viewers
5. One specific actionable recommendation for the next video

Then send an email to d.mcderm80@gmail.com via Gmail with:
- Subject: "YouTube Comments Summary — [date]"
- A clean, well-formatted HTML email with the analysis above
- Keep it skimmable: use headings and bullet points
- End with the raw comment counts per video

Once the email is sent, stop.
```

### Setup Steps
1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials
2. Create a new API Key, restrict it to **YouTube Data API v3**, remove HTTP referrer restrictions
3. Find your Channel ID at youtube.com/account_advanced
4. Go to claude.ai/settings → Connectors → connect Gmail
5. Go to claude.ai/code/routines → New Routine → paste the prompt above
6. Set Cloud Environment variables: `YOUTUBE_API_KEY` and `YOUTUBE_CHANNEL_ID`
7. Set Network Access to **Full**
8. Set trigger to your preferred schedule (daily or weekly)
9. Hit Run Now to verify it works end-to-end
