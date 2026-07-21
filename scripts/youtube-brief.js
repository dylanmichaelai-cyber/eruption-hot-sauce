#!/usr/bin/env node
/**
 * Fetches recent YouTube video comments for a channel and outputs
 * structured JSON for Claude to analyze and summarize via email.
 *
 * Usage:
 *   YOUTUBE_API_KEY=<key> CHANNEL_ID=<id> node scripts/youtube-brief.js
 *
 * Output: JSON written to stdout
 */

const API_KEY = process.env.YOUTUBE_API_KEY;
const CHANNEL_ID = process.env.CHANNEL_ID;
const MAX_VIDEOS = parseInt(process.env.MAX_VIDEOS || '10', 10);
const MAX_COMMENTS_PER_VIDEO = parseInt(process.env.MAX_COMMENTS_PER_VIDEO || '50', 10);

if (!API_KEY || !CHANNEL_ID) {
  console.error(JSON.stringify({
    error: 'Missing required env vars: YOUTUBE_API_KEY and CHANNEL_ID',
  }));
  process.exit(1);
}

const BASE = 'https://www.googleapis.com/youtube/v3';

async function get(path, params) {
  const url = new URL(`${BASE}/${path}`);
  url.searchParams.set('key', API_KEY);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url.toString());
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`YouTube API ${path} → ${res.status}: ${body}`);
  }
  return res.json();
}

async function getRecentVideos() {
  const data = await get('search', {
    part: 'snippet',
    channelId: CHANNEL_ID,
    order: 'date',
    type: 'video',
    maxResults: MAX_VIDEOS,
  });
  return (data.items || []).map(item => ({
    id: item.id.videoId,
    title: item.snippet.title,
    publishedAt: item.snippet.publishedAt,
    description: item.snippet.description.slice(0, 200),
  }));
}

async function getComments(videoId) {
  try {
    const data = await get('commentThreads', {
      part: 'snippet',
      videoId,
      order: 'relevance',
      maxResults: MAX_COMMENTS_PER_VIDEO,
      textFormat: 'plainText',
    });
    return (data.items || []).map(item => {
      const c = item.snippet.topLevelComment.snippet;
      return {
        author: c.authorDisplayName,
        text: c.textDisplay.slice(0, 500),
        likes: c.likeCount,
        publishedAt: c.publishedAt,
      };
    });
  } catch (e) {
    // Comments may be disabled on some videos
    return [];
  }
}

async function getChannelInfo() {
  const data = await get('channels', {
    part: 'snippet,statistics',
    id: CHANNEL_ID,
  });
  const ch = data.items?.[0];
  if (!ch) throw new Error(`Channel ${CHANNEL_ID} not found`);
  return {
    title: ch.snippet.title,
    subscribers: ch.statistics.subscriberCount,
    totalViews: ch.statistics.viewCount,
    videoCount: ch.statistics.videoCount,
  };
}

async function main() {
  const [channel, videos] = await Promise.all([
    getChannelInfo(),
    getRecentVideos(),
  ]);

  const videosWithComments = await Promise.all(
    videos.map(async video => ({
      ...video,
      comments: await getComments(video.id),
    }))
  );

  const result = {
    fetchedAt: new Date().toISOString(),
    channel,
    videos: videosWithComments,
    totalCommentsFetched: videosWithComments.reduce((n, v) => n + v.comments.length, 0),
  };

  process.stdout.write(JSON.stringify(result, null, 2));
}

main().catch(e => {
  console.error(JSON.stringify({ error: e.message }));
  process.exit(1);
});
