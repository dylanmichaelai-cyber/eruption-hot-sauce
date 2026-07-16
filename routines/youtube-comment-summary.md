# YouTube Comment Summary Routine

Fetches recent comments from Dylan's YouTube channel, analyzes sentiment and improvement areas, and emails a weekly summary to d.mcderm80@gmail.com.

## Schedule

Runs every Monday at 8:17am local time.

## Setup Requirements

1. YouTube Data API v3 key with the following APIs enabled in Google Cloud Console:
   - YouTube Data API v3

2. Gmail connector connected at claude.ai/settings → Connectors

3. Environment variable in the Routine's Cloud Environment settings:
   - `YOUTUBE_API_KEY` — your YouTube Data API v3 key

## Routine Prompt

```
You are running a scheduled YouTube Comment Analysis routine for Dylan. Complete every step.

**STEP 1 — Fetch channel info**
Run this curl command and extract the channel ID (items[0].id) and uploads playlist ID (items[0].contentDetails.relatedPlaylists.uploads):

curl -s "https://www.googleapis.com/youtube/v3/channels?part=snippet,contentDetails&forHandle=dylanmichaelai&key=$YOUTUBE_API_KEY"

**STEP 2 — Fetch 10 most recent videos**
Run this curl command using the uploads playlist ID from step 1:

curl -s "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={UPLOADS_PLAYLIST_ID}&maxResults=10&key=$YOUTUBE_API_KEY"

Collect each video's ID and title.

**STEP 3 — Fetch comments for the 5 most recent videos**
For each of the 5 most recent videos, run:

curl -s "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={VIDEO_ID}&maxResults=100&order=relevance&key=$YOUTUBE_API_KEY"

Collect the text, author, and like count of every top-level comment.

**STEP 4 — Analyze comments**
Review all collected comments and produce a structured analysis:
- Overall sentiment breakdown (positive / neutral / negative with approximate percentages)
- Top themes — what viewers consistently love
- Recurring criticisms or complaints
- Content/feature requests viewers mention
- Top 3–5 specific, actionable improvement recommendations grounded in what viewers actually said
- 3–5 of the most liked or insightful comments worth highlighting

**STEP 5 — Draft the summary email**
Call mcp__Gmail__create_draft with:
- to: ["d.mcderm80@gmail.com"]
- subject: "YouTube Comment Summary — Week of [today's date]"
- htmlBody: A clean HTML email containing the full analysis from Step 4, organized with clear headings, bullet points, and comment excerpts. Include each video title analyzed. If any API call failed, include the error so Dylan can fix it.
```

## Notes

- The API key must be enabled for YouTube Data API v3 — if you see "API Key not found", go to console.cloud.google.com, open your project, navigate to APIs & Services → Credentials, and verify the key exists and YouTube Data API v3 is enabled under APIs & Services → Library.
- Comments are fetched in relevance order (most liked first), so the analysis reflects the most impactful feedback.
- Gmail drafts are created (not sent automatically) — Dylan reviews and sends them manually.
