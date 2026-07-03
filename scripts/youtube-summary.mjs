#!/usr/bin/env node
/**
 * Fetches recent YouTube video comments for a channel and prints JSON to stdout.
 *
 * Required env vars:
 *   YOUTUBE_API_KEY      — YouTube Data API v3 key
 *
 * Optional env vars:
 *   YOUTUBE_CHANNEL_ID   — skip auto-discovery and use this channel ID directly
 *   YOUTUBE_CHANNEL_QUERY — search query to find the channel (default: "Eruption Hot Sauce")
 *   VIDEOS_TO_CHECK      — how many recent videos to pull comments from (default: 8)
 *   COMMENTS_PER_VIDEO   — max comments per video (default: 100)
 */

const API_KEY      = process.env.YOUTUBE_API_KEY;
const CHANNEL_ID   = process.env.YOUTUBE_CHANNEL_ID || "";
const CHANNEL_Q    = process.env.YOUTUBE_CHANNEL_QUERY || "Eruption Hot Sauce";
const VIDEO_LIMIT  = parseInt(process.env.VIDEOS_TO_CHECK   || "8",  10);
const CMT_LIMIT    = parseInt(process.env.COMMENTS_PER_VIDEO || "100", 10);
const BASE         = "https://www.googleapis.com/youtube/v3";

if (!API_KEY) {
  console.error("Error: YOUTUBE_API_KEY env var is required.");
  process.exit(1);
}

async function ytFetch(path) {
  const url = `${BASE}${path}${path.includes("?") ? "&" : "?"}key=${API_KEY}`;
  const res  = await fetch(url);
  const json = await res.json();
  if (json.error) throw new Error(`YouTube API error (${json.error.code}): ${json.error.message}`);
  return json;
}

async function resolveChannelId() {
  if (CHANNEL_ID) return CHANNEL_ID;

  const data = await ytFetch(
    `/search?part=snippet&q=${encodeURIComponent(CHANNEL_Q)}&type=channel&maxResults=5`
  );

  if (!data.items || data.items.length === 0)
    throw new Error(`No channel found for query "${CHANNEL_Q}"`);

  // Pick the first result; log candidates so the caller can verify
  const candidates = data.items.map(i => ({
    id:    i.snippet.channelId,
    title: i.snippet.channelTitle,
  }));
  process.stderr.write(`Channel candidates: ${JSON.stringify(candidates)}\n`);
  return candidates[0].id;
}

async function getRecentVideos(channelId) {
  const data = await ytFetch(
    `/search?part=snippet&channelId=${channelId}&type=video&order=date&maxResults=${VIDEO_LIMIT}`
  );
  return (data.items || []).map(v => ({
    videoId: v.id.videoId,
    title:   v.snippet.title,
    published: v.snippet.publishedAt,
  }));
}

async function getComments(videoId) {
  try {
    const data = await ytFetch(
      `/commentThreads?part=snippet&videoId=${videoId}&maxResults=${CMT_LIMIT}&order=relevance&textFormat=plainText`
    );
    return (data.items || []).map(item => {
      const c = item.snippet.topLevelComment.snippet;
      return {
        author: c.authorDisplayName,
        text:   c.textDisplay,
        likes:  c.likeCount,
        date:   c.publishedAt,
        replyCount: item.snippet.totalReplyCount,
      };
    });
  } catch (err) {
    // Comments may be disabled on some videos
    process.stderr.write(`Comments unavailable for ${videoId}: ${err.message}\n`);
    return [];
  }
}

async function main() {
  const channelId = await resolveChannelId();
  process.stderr.write(`Using channel ID: ${channelId}\n`);

  const videos = await getRecentVideos(channelId);
  process.stderr.write(`Fetching comments for ${videos.length} videos…\n`);

  const results = [];
  for (const video of videos) {
    const comments = await getComments(video.videoId);
    results.push({ ...video, commentCount: comments.length, comments });
  }

  const totalComments = results.reduce((n, v) => n + v.commentCount, 0);
  const output = {
    fetchedAt: new Date().toISOString(),
    channelId,
    videoCount: results.length,
    totalComments,
    videos: results,
  };

  process.stdout.write(JSON.stringify(output, null, 2) + "\n");
}

main().catch(err => { console.error(err.message); process.exit(1); });
