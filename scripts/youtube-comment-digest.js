#!/usr/bin/env node
/**
 * YouTube Comment Digest
 * Fetches recent comments from your YouTube channel videos and outputs
 * a structured JSON summary for Claude to analyze and email.
 *
 * Config: scripts/youtube-config.json
 * Usage: node scripts/youtube-comment-digest.js
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const cfg = JSON.parse(readFileSync(join(__dirname, 'youtube-config.json'), 'utf8'));

const BASE = 'https://www.googleapis.com/youtube/v3';

async function get(path, params) {
  const url = new URL(BASE + path);
  url.searchParams.set('key', cfg.apiKey);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(`YouTube API ${res.status}: ${err?.error?.message ?? res.statusText}`);
  }
  return res.json();
}

async function getRecentVideos(channelId, maxResults = 10) {
  const data = await get('/search', {
    part: 'snippet',
    channelId,
    type: 'video',
    order: 'date',
    maxResults,
  });
  return data.items.map(i => ({
    videoId: i.id.videoId,
    title: i.snippet.title,
    publishedAt: i.snippet.publishedAt,
  }));
}

async function getComments(videoId, maxResults = 50) {
  try {
    const data = await get('/commentThreads', {
      part: 'snippet',
      videoId,
      order: 'relevance',
      maxResults,
    });
    return data.items.map(i => {
      const c = i.snippet.topLevelComment.snippet;
      return {
        author: c.authorDisplayName,
        text: c.textDisplay,
        likes: c.likeCount,
        publishedAt: c.publishedAt,
      };
    });
  } catch (e) {
    if (e.message.includes('disabled comments') || e.message.includes('403')) return [];
    throw e;
  }
}

async function main() {
  const channelId = cfg.channelId;
  if (!channelId || channelId === 'YOUR_CHANNEL_ID') {
    throw new Error('Set channelId in scripts/youtube-config.json');
  }

  const videos = await getRecentVideos(channelId, cfg.videosToCheck ?? 10);
  const results = [];

  for (const video of videos) {
    const comments = await getComments(video.videoId, cfg.commentsPerVideo ?? 50);
    results.push({ ...video, comments, commentCount: comments.length });
  }

  const output = {
    fetchedAt: new Date().toISOString(),
    channelId,
    videos: results,
    totalComments: results.reduce((sum, v) => sum + v.commentCount, 0),
  };

  process.stdout.write(JSON.stringify(output, null, 2));
}

main().catch(e => { console.error(e.message); process.exit(1); });
