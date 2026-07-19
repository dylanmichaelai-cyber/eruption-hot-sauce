#!/usr/bin/env node
/**
 * Fetches recent YouTube comments for a channel and prints structured JSON to stdout.
 *
 * Env vars:
 *   YOUTUBE_API_KEY          – required
 *   YOUTUBE_CHANNEL_ID       – preferred; skips handle lookup if set
 *   YOUTUBE_CHANNEL_HANDLE   – fallback (default: "EruptionHotSauce")
 *   MAX_VIDEOS               – number of recent videos to check (default: 10)
 *   MAX_COMMENTS_PER_VIDEO   – comments to pull per video (default: 50)
 */

const API_KEY      = process.env.YOUTUBE_API_KEY;
const CHANNEL_ID_ENV    = process.env.YOUTUBE_CHANNEL_ID || '';
const CHANNEL_HANDLE    = process.env.YOUTUBE_CHANNEL_HANDLE || 'EruptionHotSauce';
const MAX_VIDEOS        = parseInt(process.env.MAX_VIDEOS || '10', 10);
const MAX_COMMENTS      = parseInt(process.env.MAX_COMMENTS_PER_VIDEO || '50', 10);
const BASE              = 'https://www.googleapis.com/youtube/v3';

if (!API_KEY) {
  console.error(JSON.stringify({ error: 'YOUTUBE_API_KEY env var is required' }));
  process.exit(1);
}

async function ytGet(endpoint, params) {
  const url = new URL(`${BASE}/${endpoint}`);
  url.searchParams.set('key', API_KEY);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const res = await fetch(url.toString());
  const body = await res.text();
  if (!res.ok) throw new Error(`YouTube API ${res.status} on ${endpoint}: ${body}`);
  return JSON.parse(body);
}

async function resolveChannelId() {
  if (CHANNEL_ID_ENV) return CHANNEL_ID_ENV;

  // 1. Try by handle (e.g. @EruptionHotSauce)
  try {
    const handle = CHANNEL_HANDLE.replace(/^@/, '');
    const d = await ytGet('channels', { part: 'id', forHandle: handle });
    if (d.items?.length) return d.items[0].id;
  } catch (_) {}

  // 2. Try legacy username
  try {
    const d = await ytGet('channels', { part: 'id', forUsername: CHANNEL_HANDLE });
    if (d.items?.length) return d.items[0].id;
  } catch (_) {}

  // 3. Search by name
  try {
    const d = await ytGet('search', {
      part: 'id', type: 'channel', q: CHANNEL_HANDLE, maxResults: 1,
    });
    if (d.items?.length) return d.items[0].id.channelId;
  } catch (_) {}

  return null;
}

async function getRecentVideos(channelId) {
  const d = await ytGet('search', {
    part: 'id,snippet', channelId, type: 'video',
    order: 'date', maxResults: MAX_VIDEOS,
  });
  return (d.items || []).map(item => ({
    videoId:     item.id.videoId,
    title:       item.snippet.title,
    publishedAt: item.snippet.publishedAt,
    url:         `https://www.youtube.com/watch?v=${item.id.videoId}`,
    description: item.snippet.description?.slice(0, 200),
  }));
}

async function getComments(videoId) {
  try {
    const d = await ytGet('commentThreads', {
      part: 'snippet', videoId, maxResults: MAX_COMMENTS, order: 'relevance',
    });
    return (d.items || []).map(item => {
      const c = item.snippet.topLevelComment.snippet;
      return {
        text:        c.textDisplay.replace(/<[^>]*>/g, '').trim(),
        author:      c.authorDisplayName,
        likes:       c.likeCount,
        publishedAt: c.publishedAt,
        replyCount:  item.snippet.totalReplyCount,
      };
    });
  } catch {
    return [];
  }
}

async function main() {
  const channelId = await resolveChannelId();
  if (!channelId) {
    console.error(JSON.stringify({
      error: `Could not resolve YouTube channel for handle "${CHANNEL_HANDLE}". ` +
             'Set YOUTUBE_CHANNEL_ID env var to the exact channel ID.',
    }));
    process.exit(1);
  }

  const videos  = await getRecentVideos(channelId);
  const results = [];

  for (const video of videos) {
    const comments = await getComments(video.videoId);
    results.push({ ...video, commentCount: comments.length, comments });
  }

  const totalComments = results.reduce((s, v) => s + v.commentCount, 0);
  console.log(JSON.stringify({
    channelId,
    fetchedAt:     new Date().toISOString(),
    totalVideos:   results.length,
    totalComments,
    videos:        results,
  }, null, 2));
}

main().catch(err => {
  console.error(JSON.stringify({ error: err.message }));
  process.exit(1);
});
