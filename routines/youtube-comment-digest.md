# YouTube Comment Digest — Routine Prompt

> Copy the prompt below (everything inside the code block) into the prompt box at claude.ai/code/routines.
> 
> **Before running:**
> 1. Go to claude.ai/settings → Connectors → connect Gmail
> 2. In Cloud Environment settings, add these environment variables:
>    - `YOUTUBE_API_KEY` = your YouTube Data API v3 key
>    - `YOUTUBE_CHANNEL_ID` = your channel ID (find it at youtube.com/account_advanced)
> 3. Set Network Access to **Full**
> 4. Set trigger to **Weekly** (e.g. Monday 8am)

---

## Routine Prompt

```
You are running a weekly YouTube comment digest for Dylan McDermott.

Step 1 — Get the uploads playlist ID:
Call https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id={YOUTUBE_CHANNEL_ID}&key={YOUTUBE_API_KEY}
Extract the uploads playlist ID from the response (contentDetails.relatedPlaylists.uploads).

Step 2 — Get the 10 most recent videos:
Call https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={UPLOADS_PLAYLIST_ID}&maxResults=10&key={YOUTUBE_API_KEY}
Collect each videoId and videoTitle.

Step 3 — Fetch comments for each video:
For each videoId, call https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={VIDEO_ID}&maxResults=100&order=relevance&key={YOUTUBE_API_KEY}
Collect the comment text, author name, like count, and published date from snippet.topLevelComment.snippet.

Step 4 — Analyze all comments and produce:
- Overall sentiment breakdown: what percentage feel positive, neutral, or negative
- Top 5 things viewers love (specific, quoted where possible)
- Top 5 improvement suggestions (specific and actionable)
- Recurring questions viewers keep asking
- Any standout individual comments worth reading

Step 5 — Create a Gmail draft:
Use Gmail to create a draft email with:
  To: d.mcderm80@gmail.com
  Subject: YouTube Comment Digest — [today's date]
  Body: the full analysis formatted with clear section headers and bullet points

Keep the email direct and actionable. Lead with the most important insight. No filler sentences.

When the draft is saved, stop.
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `API Key not found` | The key may have IP restrictions — remove them in Google Cloud Console, or regenerate a key with no restrictions |
| `quotaExceeded` | YouTube Data API has a 10,000 unit/day quota. Each commentThreads call costs ~1 unit. This routine uses ~12 units total |
| Gmail draft not saving | Make sure Gmail is connected in Connectors settings and added to this routine's connector list |
| Channel not found | Double-check YOUTUBE_CHANNEL_ID — it starts with `UC` followed by 22 characters |
