#!/usr/bin/env node
// Fetches recent video comments from a YouTube channel using the Data API v3.
// Outputs JSON to stdout for analysis by Claude.
//
// Required env vars (set in scripts/.env or export manually):
//   YOUTUBE_API_KEY   - YouTube Data API v3 key
//   YOUTUBE_CHANNEL_ID - Your channel ID (e.g. UCxxxxxxxxxxxxxxx)
//
// Optional:
//   MAX_VIDEOS   - how many recent videos to scan (default: 5)
//   MAX_COMMENTS - comments per video (default: 50)

const https = require('https');

const API_KEY     = process.env.YOUTUBE_API_KEY;
const CHANNEL_ID  = process.env.YOUTUBE_CHANNEL_ID;
const MAX_VIDEOS  = parseInt(process.env.MAX_VIDEOS  || '5',  10);
const MAX_COMMENTS= parseInt(process.env.MAX_COMMENTS|| '50', 10);

if (!API_KEY || !CHANNEL_ID) {
  console.error(JSON.stringify({
    error: 'Missing configuration',
    missing: [
      ...(!API_KEY     ? ['YOUTUBE_API_KEY']    : []),
      ...(!CHANNEL_ID  ? ['YOUTUBE_CHANNEL_ID'] : []),
    ],
    hint: 'Set these in scripts/.env or as environment variables.',
  }));
  process.exit(1);
}

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) reject(new Error(`YouTube API: ${parsed.error.message}`));
          else resolve(parsed);
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

function qs(params) {
  return Object.entries(params)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');
}

async function getRecentVideos() {
  const params = qs({
    part: 'snippet',
    channelId: CHANNEL_ID,
    maxResults: MAX_VIDEOS,
    order: 'date',
    type: 'video',
    key: API_KEY,
  });
  const data = await get(`https://www.googleapis.com/youtube/v3/search?${params}`);
  return (data.items || []).map(item => ({
    id: item.id.videoId,
    title: item.snippet.title,
    publishedAt: item.snippet.publishedAt,
  }));
}

async function getComments(videoId, videoTitle) {
  const params = qs({
    part: 'snippet',
    videoId,
    maxResults: MAX_COMMENTS,
    order: 'relevance',
    key: API_KEY,
  });
  let data;
  try {
    data = await get(`https://www.googleapis.com/youtube/v3/commentThreads?${params}`);
  } catch (e) {
    // Comments disabled or video not found — skip gracefully
    return { videoId, videoTitle, commentsDisabled: true, comments: [] };
  }

  const comments = (data.items || []).map(item => {
    const top = item.snippet.topLevelComment.snippet;
    return {
      author: top.authorDisplayName,
      text: top.textOriginal,
      likes: top.likeCount,
      publishedAt: top.publishedAt,
    };
  });

  return { videoId, videoTitle, commentsDisabled: false, comments };
}

async function main() {
  const videos = await getRecentVideos();

  if (!videos.length) {
    console.log(JSON.stringify({ channel: CHANNEL_ID, videos: [], message: 'No recent videos found.' }));
    return;
  }

  const results = await Promise.all(videos.map(v => getComments(v.id, v.title)));
  const output = {
    channel: CHANNEL_ID,
    fetchedAt: new Date().toISOString(),
    videoCount: videos.length,
    videos: results,
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error(JSON.stringify({ error: err.message }));
  process.exit(1);
});
