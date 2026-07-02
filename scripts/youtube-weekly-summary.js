#!/usr/bin/env node
// YouTube Weekly Comment Summary
// Usage: YOUTUBE_CHANNEL_ID=UCxxxxxx ANTHROPIC_API_KEY=sk-... node scripts/youtube-weekly-summary.js
// Requires Node.js 18+ (built-in fetch)

const YOUTUBE_API_KEY = 'AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c';
const CHANNEL_ID = process.env.YOUTUBE_CHANNEL_ID;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const MAX_VIDEOS = 5;
const MAX_COMMENTS_PER_VIDEO = 100;

async function fetchJson(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(`YouTube API error ${res.status}: ${data?.error?.message || url}`);
  return data;
}

async function getRecentVideos() {
  const data = await fetchJson(
    `https://www.googleapis.com/youtube/v3/search?part=snippet&channelId=${CHANNEL_ID}` +
    `&maxResults=${MAX_VIDEOS}&order=date&type=video&key=${YOUTUBE_API_KEY}`
  );
  return (data.items || []).map(item => ({
    id: item.id.videoId,
    title: item.snippet.title,
    publishedAt: item.snippet.publishedAt,
    description: item.snippet.description?.slice(0, 200),
  }));
}

async function getVideoComments(videoId) {
  try {
    const data = await fetchJson(
      `https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId=${videoId}` +
      `&maxResults=${MAX_COMMENTS_PER_VIDEO}&order=relevance&key=${YOUTUBE_API_KEY}`
    );
    return (data.items || []).map(item => {
      const c = item.snippet.topLevelComment.snippet;
      return { text: c.textDisplay, likes: c.likeCount, author: c.authorDisplayName };
    });
  } catch {
    return []; // Comments disabled on this video
  }
}

async function analyzeWithClaude(videoData) {
  if (!ANTHROPIC_API_KEY) {
    console.warn('No ANTHROPIC_API_KEY set — skipping AI analysis');
    return null;
  }

  const commentDump = videoData.map(({ video, comments }) => {
    const topComments = comments
      .sort((a, b) => b.likes - a.likes)
      .slice(0, 30)
      .map(c => `[${c.likes} likes] ${c.text}`)
      .join('\n');
    return `VIDEO: "${video.title}" (${video.publishedAt.slice(0, 10)})\n${topComments || '(no comments)'}`;
  }).join('\n\n---\n\n');

  const prompt = `You are analyzing YouTube comments for a content creator. Review these comments across their ${videoData.length} most recent videos and produce a detailed weekly digest.

${commentDump}

Produce a structured analysis with these sections:
1. OVERALL SENTIMENT — % positive / neutral / negative with a 2-sentence summary of the mood
2. WHAT VIEWERS LOVE — Top 3 specific things praised, each with 1-2 real quotes as evidence
3. TOP IMPROVEMENT AREAS — Top 3 actionable, constructive suggestions drawn from viewer feedback (be specific, not generic)
4. COMMON QUESTIONS — Questions viewers are asking that the creator could address in future videos
5. STANDOUT COMMENTS — 3 to 5 comments worth reading verbatim (most insightful, funniest, or most-liked)
6. VIDEO-BY-VIDEO BREAKDOWN — One sentence per video on sentiment and themes
7. RECOMMENDED NEXT STEPS — 2-3 specific content or style ideas based on what the audience is saying

Be honest and constructive. Focus on actionable insights the creator can use.`;

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: 'claude-opus-4-8',
      max_tokens: 2048,
      messages: [{ role: 'user', content: prompt }],
    }),
  });

  const result = await res.json();
  if (!res.ok) throw new Error(`Anthropic API error: ${result?.error?.message}`);
  return result.content[0].text;
}

async function main() {
  if (!CHANNEL_ID) {
    console.error('Error: Set the YOUTUBE_CHANNEL_ID environment variable to your YouTube channel ID (e.g. UCxxxxxxxxxxxxxx)');
    process.exit(1);
  }

  console.log(`Fetching recent videos for channel ${CHANNEL_ID}...`);
  const videos = await getRecentVideos();

  if (videos.length === 0) {
    console.log('No videos found. Check your channel ID.');
    return;
  }

  console.log(`Found ${videos.length} videos. Fetching comments...`);
  const videoData = [];
  for (const video of videos) {
    const comments = await getVideoComments(video.id);
    console.log(`  "${video.title}" — ${comments.length} comments`);
    videoData.push({ video, comments });
  }

  const totalComments = videoData.reduce((n, d) => n + d.comments.length, 0);
  console.log(`\nTotal comments collected: ${totalComments}`);

  const analysis = await analyzeWithClaude(videoData);

  if (analysis) {
    console.log('\n' + '='.repeat(60));
    console.log('YOUTUBE WEEKLY COMMENT DIGEST');
    console.log('='.repeat(60) + '\n');
    console.log(analysis);
  } else {
    for (const { video, comments } of videoData) {
      console.log(`\n"${video.title}": ${comments.length} comments`);
      comments.slice(0, 5).forEach(c => console.log(`  [${c.likes}♥] ${c.text.slice(0, 120)}`));
    }
  }
}

main().catch(err => { console.error(err.message); process.exit(1); });
