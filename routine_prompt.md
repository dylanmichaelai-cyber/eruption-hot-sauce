# Claude Code Routine — YouTube Comment Digest

## Setup (one time)
1. Go to **claude.ai/settings → Connectors** and connect **Gmail**
2. In **Cloud Environment → Environment Variables**, add:
   - `YOUTUBE_API_KEY` = `AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c`
   - `CHANNEL_ID` = your YouTube channel ID
3. Set **Network Access** to **Full**

---

## Routine Prompt (paste this into the Routine builder)

```
You are my YouTube analytics assistant. Do the following steps in order and do not stop until all steps are complete.

STEP 1 — Fetch recent videos
Use the YouTube Data API v3 with the API key in the YOUTUBE_API_KEY environment variable.
Call: GET https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={CHANNEL_ID}&maxResults=5&order=date&type=video&key={YOUTUBE_API_KEY}
Collect the video IDs and titles of the 5 most recent videos.

STEP 2 — Fetch comments for each video
For each video ID, call:
GET https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={VIDEO_ID}&maxResults=50&order=relevance&textFormat=plainText&key={YOUTUBE_API_KEY}
Collect all the comment text and like counts.

STEP 3 — Analyze the comments
Review all comments you collected and produce a structured analysis with these sections:
1. Overall Sentiment — a short paragraph on how viewers feel in general
2. What People Love — 3 to 5 bullet points on what viewers praise most
3. Criticism & Concerns — 3 to 5 bullet points on the most common complaints
4. Actionable Improvements — 5 specific things I can do differently in future videos based on viewer feedback
5. Notable Comments — 2 to 3 standout comments worth reading

STEP 4 — Send a summary email via Gmail
Use the Gmail connector to send an email to my Gmail address with:
- Subject: "YouTube Comment Digest — [today's date]"
- Body: the full analysis from Step 3, formatted clearly with headers and bullet points
- Include a list of the video titles analyzed at the top of the email

Once the email is sent, stop.
```

---

## Recommended trigger
- **Schedule**: Daily or weekly (e.g. every Monday at 8am)

## Notes
- If you see a `disabled_comments` error for a video, skip it and continue with the rest.
- The analysis should be honest — do not soften criticism.
