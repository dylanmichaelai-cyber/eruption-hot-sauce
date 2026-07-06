#!/usr/bin/env node
// Fetches recent comments from a YouTube channel's videos.
// Outputs JSON: { channelTitle, videos: [{ title, videoId, url, comments: [...] }], fetchedAt }
// Usage: node fetch-youtube-comments.js

const https = require('https');

const API_KEY    = process.env.YOUTUBE_API_KEY    || 'AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c';
const CHANNEL_ID = process.env.YOUTUBE_CHANNEL_ID || '';  // Set via env or config.json
const MAX_VIDEOS  = 10;   // how many recent videos to check
const MAX_COMMENTS_PER_VIDEO = 50;

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error('JSON parse error: ' + data.slice(0, 200))); }
      });
    }).on('error', reject);
  });
}

async function getChannelId() {
  if (CHANNEL_ID) return CHANNEL_ID;
  // Try to look up by handle if YOUTUBE_HANDLE is set
  const handle = process.env.YOUTUBE_HANDLE;
  if (handle) {
    const url = `https://www.googleapis.com/youtube/v3/channels?part=snippet&forHandle=${encodeURIComponent(handle)}&key=${API_KEY}`;
    const data = await get(url);
    if (data.items && data.items.length > 0) return data.items[0].id;
  }
  throw new Error('No channel ID found. Set YOUTUBE_CHANNEL_ID or YOUTUBE_HANDLE env var.');
}

async function getRecentVideos(channelId) {
  const url = `https://www.googleapis.com/youtube/v3/search?part=snippet&channelId=${channelId}&order=date&type=video&maxResults=${MAX_VIDEOS}&key=${API_KEY}`;
  const data = await get(url);
  if (data.error) throw new Error('YouTube API error: ' + JSON.stringify(data.error));
  return (data.items || []).map(item => ({
    videoId: item.id.videoId,
    title: item.snippet.title,
    publishedAt: item.snippet.publishedAt,
    url: `https://www.youtube.com/watch?v=${item.id.videoId}`,
  }));
}

async function getComments(videoId) {
  const url = `https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId=${videoId}&maxResults=${MAX_COMMENTS_PER_VIDEO}&order=relevance&key=${API_KEY}`;
  const data = await get(url);
  if (data.error) {
    // Comments may be disabled on this video — return empty
    if (data.error.errors && data.error.errors[0].reason === 'commentsDisabled') return [];
    throw new Error('YouTube API error: ' + JSON.stringify(data.error));
  }
  return (data.items || []).map(item => {
    const c = item.snippet.topLevelComment.snippet;
    return {
      author: c.authorDisplayName,
      text: c.textDisplay,
      likeCount: c.likeCount,
      publishedAt: c.publishedAt,
    };
  });
}

async function main() {
  const channelId = await getChannelId();

  // Fetch channel title
  const channelData = await get(
    `https://www.googleapis.com/youtube/v3/channels?part=snippet&id=${channelId}&key=${API_KEY}`
  );
  if (channelData.error) throw new Error('Channel lookup failed: ' + JSON.stringify(channelData.error));
  const channelTitle = channelData.items?.[0]?.snippet?.title || channelId;

  const videos = await getRecentVideos(channelId);

  const results = [];
  for (const video of videos) {
    const comments = await getComments(video.videoId);
    results.push({ ...video, commentCount: comments.length, comments });
  }

  const output = {
    channelTitle,
    channelId,
    fetchedAt: new Date().toISOString(),
    videoCount: results.length,
    videos: results,
  };

  process.stdout.write(JSON.stringify(output, null, 2));
}

main().catch(err => {
  process.stderr.write('ERROR: ' + err.message + '\n');
  process.exit(1);
});
