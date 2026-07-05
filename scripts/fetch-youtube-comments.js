#!/usr/bin/env node
// Fetches recent videos and top comments from a YouTube channel via Data API v3.
// Outputs JSON to stdout for the weekly summary cron routine.

const https = require('https');
const fs = require('fs');
const path = require('path');

const config = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'youtube-config.json'), 'utf8')
);

const { apiKey, channelId, maxVideos = 10, maxCommentsPerVideo = 100, daysBack = 7 } = config;

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => (data += chunk));
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`Bad JSON from API: ${data.slice(0, 200)}`)); }
      });
    }).on('error', reject);
  });
}

async function fetchRecentVideos() {
  const since = new Date();
  since.setDate(since.getDate() - daysBack);

  const url =
    `https://www.googleapis.com/youtube/v3/search?` +
    `part=snippet&channelId=${channelId}&type=video&order=date` +
    `&publishedAfter=${since.toISOString()}&maxResults=${maxVideos}&key=${apiKey}`;

  const data = await get(url);
  if (data.error) throw new Error(`YouTube API: ${data.error.message}`);
  return data.items || [];
}

async function fetchAllVideosFromChannel() {
  // Fall back to fetching latest N videos regardless of date if none in window
  const url =
    `https://www.googleapis.com/youtube/v3/search?` +
    `part=snippet&channelId=${channelId}&type=video&order=date` +
    `&maxResults=${maxVideos}&key=${apiKey}`;

  const data = await get(url);
  if (data.error) throw new Error(`YouTube API: ${data.error.message}`);
  return data.items || [];
}

async function fetchComments(videoId, videoTitle, publishedAt) {
  const url =
    `https://www.googleapis.com/youtube/v3/commentThreads?` +
    `part=snippet&videoId=${videoId}&maxResults=${maxCommentsPerVideo}` +
    `&order=relevance&key=${apiKey}`;

  try {
    const data = await get(url);
    if (data.error) {
      // Comments may be disabled on some videos
      return { videoId, videoTitle, publishedAt, commentsDisabled: true, comments: [] };
    }

    const comments = (data.items || []).map((item) => {
      const s = item.snippet.topLevelComment.snippet;
      return {
        author: s.authorDisplayName,
        text: s.textDisplay,
        likes: s.likeCount,
        replies: item.snippet.totalReplyCount,
        publishedAt: s.publishedAt,
      };
    });

    return { videoId, videoTitle, publishedAt, commentCount: comments.length, comments };
  } catch (e) {
    return { videoId, videoTitle, publishedAt, error: e.message, comments: [] };
  }
}

async function main() {
  if (!channelId || channelId === 'YOUR_CHANNEL_ID') {
    process.stderr.write('ERROR: Set channelId in scripts/youtube-config.json\n');
    process.exit(1);
  }

  let videos = await fetchRecentVideos();
  const windowUsed = videos.length > 0 ? `last ${daysBack} days` : 'latest (no recent uploads)';
  if (videos.length === 0) videos = await fetchAllVideosFromChannel();

  const videoData = [];
  for (const video of videos) {
    const id = video.id.videoId;
    if (!id) continue;
    const result = await fetchComments(id, video.snippet.title, video.snippet.publishedAt);
    videoData.push(result);
  }

  const totalComments = videoData.reduce((n, v) => n + v.comments.length, 0);

  process.stdout.write(
    JSON.stringify(
      {
        channelId,
        window: windowUsed,
        fetchedAt: new Date().toISOString(),
        totalVideos: videoData.length,
        totalComments,
        videos: videoData,
      },
      null,
      2
    ) + '\n'
  );
}

main().catch((err) => {
  process.stderr.write(`FATAL: ${err.message}\n`);
  process.exit(1);
});
