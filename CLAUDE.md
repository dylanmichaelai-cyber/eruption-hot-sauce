# Eruption Hot Sauce — Claude Context

## About This Channel
This is a YouTube channel about Eruption Hot Sauce — an ultra-premium hot sauce brand.
Videos cover topics like heat levels, ingredients, flavor profiles, reviews, and the brand story.
The audience ranges from casual hot sauce fans to hardcore heat enthusiasts.
The channel owner's email is d.mcderm80@gmail.com.

## YouTube Comments Routine

### What This Routine Does
Runs on a schedule, fetches recent YouTube comments, analyzes viewer sentiment and feedback,
then saves a formatted summary as a Gmail draft to d.mcderm80@gmail.com.

### Routine Prompt (copy this into claude.ai/code/routines)

```
Run the YouTube comments script to fetch recent comments:

  node scripts/fetch-youtube-comments.js

Wait for it to finish. Then analyze the JSON output it prints and extract:

1. SENTIMENT BREAKDOWN — rough percentage of positive, neutral, and negative comments
2. WHAT VIEWERS LOVE — top 3 recurring themes people praise (be specific, quote examples)
3. WHAT NEEDS IMPROVEMENT — top 3 recurring criticisms or requests (be specific, quote examples)
4. ACTIONABLE RECOMMENDATIONS — 3 concrete things I can do in my next video based on this feedback

Format the findings as a clean HTML email and save it as a Gmail draft to d.mcderm80@gmail.com
with the subject: "YouTube Feedback Summary – [today's date]"

Once the draft is saved, stop.
```

### Required Environment Variables
Set these in the Cloud Environment section of your Routine:

| Variable | Value |
|---|---|
| `YOUTUBE_API_KEY` | `AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c` |
| `YOUTUBE_CHANNEL_ID` | Your channel ID — find it at youtube.com/account_advanced |

### Recommended Schedule
Daily at 8:00 AM — gives you a fresh summary every morning before you start work.

### Setup Checklist
- [ ] Go to claude.ai/settings → Connectors → connect Gmail (do this before building the routine)
- [ ] Go to claude.ai/code/routines → New Routine
- [ ] Name it: **YouTube Comment Digest**
- [ ] Paste the prompt from above
- [ ] Select this repo: `dylanmichaelai-cyber/eruption-hot-sauce`
- [ ] Set trigger: Schedule → Daily → 8:00 AM
- [ ] Add Gmail connector
- [ ] Click Cloud Environment (gear icon) → paste both env vars → set Network Access to **Full**
- [ ] Click Create
- [ ] Click Run Now to verify it works end-to-end before relying on the schedule
