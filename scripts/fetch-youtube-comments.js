#!/usr/bin/env node
/**
 * Fetches recent comments from your YouTube channel's videos.
 * Outputs structured JSON to stdout for Claude to analyze.
 *
 * Required env vars:
 *   YOUTUBE_API_KEY      — YouTube Data API v3 key
 *   YOUTUBE_CHANNEL_ID   — Your channel ID (found at youtube.com/account_advanced)
 *
 * Optional env vars:
 *   MAX_VIDEOS           — How many recent videos to check (default: 5)
 *   MAX_COMMENTS_PER_VIDEO — Comments to pull per video (default: 50)
 */

const API_KEY = process.env.YOUTUBE_API_KEY;
const CHANNEL_ID = process.env.YOUTUBE_CHANNEL_ID;
const MAX_VIDEOS = parseInt(process.env.MAX_VIDEOS || '5', 10);
const MAX_COMMENTS = parseInt(process.env.MAX_COMMENTS_PER_VIDEO || '50', 10);

if (!API_KEY) {
  console.error('ERROR: YOUTUBE_API_KEY environment variable is not set.');
  process.exit(1);
}
if (!CHANNEL_ID) {
  console.error('ERROR: YOUTUBE_CHANNEL_ID environment variable is not set.');
  console.error('Find your channel ID at: https://www.youtube.com/account_advanced');
  process.exit(1);
}

async function yt(endpoint, params) {
  const url = new URL(`https://www.googleapis.com/youtube/v3/${endpoint}`);
  url.searchParams.set('key', API_KEY);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));

  const res = await fetch(url.toString());
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`YouTube API ${endpoint} failed (${res.status}): ${body}`);
  }
  return res.json();
}

async function getUploadsPlaylistId() {
  const data = await yt('channels', { part: 'contentDetails', id: CHANNEL_ID });
  if (!data.items?.length) {
    throw new Error(`Channel not found: ${CHANNEL_ID}. Check your YOUTUBE_CHANNEL_ID.`);
  }
  return data.items[0].contentDetails.relatedPlaylists.uploads;
}

async function getRecentVideos(uploadsPlaylistId) {
  const data = await yt('playlistItems', {
    part: 'snippet',
    playlistId: uploadsPlaylistId,
    maxResults: MAX_VIDEOS,
  });
  return (data.items || []).map(item => ({
    id: item.snippet.resourceId.videoId,
    title: item.snippet.title,
    publishedAt: item.snippet.publishedAt,
    url: `https://www.youtube.com/watch?v=${item.snippet.resourceId.videoId}`,
  }));
}

async function getComments(videoId) {
  try {
    const data = await yt('commentThreads', {
      part: 'snippet',
      videoId,
      maxResults: MAX_COMMENTS,
      order: 'relevance',
    });
    return (data.items || []).map(item => {
      const c = item.snippet.topLevelComment.snippet;
      return {
        author: c.authorDisplayName,
        text: c.textDisplay,
        likes: c.likeCount,
        publishedAt: c.publishedAt,
      };
    });
  } catch {
    return [];
  }
}

async function main() {
  process.stderr.write(`Fetching up to ${MAX_VIDEOS} recent videos for channel ${CHANNEL_ID}...\n`);

  const uploadsPlaylistId = await getUploadsPlaylistId();
  const videos = await getRecentVideos(uploadsPlaylistId);

  if (!videos.length) {
    console.log(JSON.stringify({ error: 'No videos found on this channel.' }));
    return;
  }

  const results = [];
  for (const video of videos) {
    process.stderr.write(`  → ${video.title}\n`);
    const comments = await getComments(video.id);
    results.push({ ...video, commentCount: comments.length, comments });
  }

  const totalComments = results.reduce((n, v) => n + v.commentCount, 0);
  process.stderr.write(`Done. Fetched ${totalComments} comments across ${videos.length} videos.\n`);

  console.log(JSON.stringify({ fetchedAt: new Date().toISOString(), videos: results }, null, 2));
}

main().catch(err => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
