# Eruption Hot Sauce — Claude Code Context

## Owner
Dylan McDermott — d.mcderm80@gmail.com  
YouTube creator focused on AI automation tools and workflows.

## YouTube Channel
- Channel ID: stored in environment variable `YOUTUBE_CHANNEL_ID`
- API Key: stored in environment variable `YOUTUBE_API_KEY`

## Routines

### YouTube Comment Digest
Runs weekly. Fetches recent YouTube comments, analyzes viewer sentiment and feedback, and emails a digest to d.mcderm80@gmail.com.

See `routines/youtube-comment-digest.md` for the full routine prompt.

## Preferences
- Email tone: direct and actionable, no filler
- Summaries should lead with the most important insight
- Improvement suggestions should be specific, not generic
