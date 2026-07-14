#!/usr/bin/env node
// Fetches YouTube comments from your channel, analyzes sentiment with Claude,
// and emails a weekly summary to RECIPIENT_EMAIL.
//
// Required env vars (set as GitHub Secrets):
//   YOUTUBE_API_KEY     — YouTube Data API v3 key
//   YOUTUBE_CHANNEL_ID  — Your channel ID (e.g. UCxxxxxxxxxxxxxxxx)
//   ANTHROPIC_API_KEY   — Anthropic API key for analysis
//   GMAIL_USER          — Gmail address used to send (e.g. you@gmail.com)
//   GMAIL_APP_PASSWORD  — Gmail App Password (not your login password)
//   RECIPIENT_EMAIL     — Where to send the summary (defaults to GMAIL_USER)

const https = require('https');
const nodemailer = require('nodemailer');
const Anthropic = require('@anthropic-ai/sdk');

const {
  YOUTUBE_API_KEY,
  YOUTUBE_CHANNEL_ID,
  ANTHROPIC_API_KEY,
  GMAIL_USER,
  GMAIL_APP_PASSWORD,
  RECIPIENT_EMAIL,
} = process.env;

function httpsGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let raw = '';
      res.on('data', (chunk) => (raw += chunk));
      res.on('end', () => {
        try {
          resolve(JSON.parse(raw));
        } catch (e) {
          reject(new Error(`JSON parse error for ${url}: ${e.message}`));
        }
      });
    }).on('error', reject);
  });
}

async function getUploadsPlaylistId() {
  const url =
    `https://www.googleapis.com/youtube/v3/channels` +
    `?part=contentDetails&id=${YOUTUBE_CHANNEL_ID}&key=${YOUTUBE_API_KEY}`;
  const data = await httpsGet(url);
  if (data.error) throw new Error(`YouTube API: ${data.error.message}`);
  if (!data.items?.length) throw new Error('Channel not found. Check YOUTUBE_CHANNEL_ID.');
  return data.items[0].contentDetails.relatedPlaylists.uploads;
}

async function getRecentVideos(uploadsPlaylistId, maxResults = 10) {
  const url =
    `https://www.googleapis.com/youtube/v3/playlistItems` +
    `?part=snippet&playlistId=${uploadsPlaylistId}&maxResults=${maxResults}&key=${YOUTUBE_API_KEY}`;
  const data = await httpsGet(url);
  if (data.error) throw new Error(`YouTube API: ${data.error.message}`);
  return (data.items || []).map((item) => ({
    id: item.snippet.resourceId.videoId,
    title: item.snippet.title,
    publishedAt: item.snippet.publishedAt,
  }));
}

async function getComments(videoId, maxResults = 100) {
  const url =
    `https://www.googleapis.com/youtube/v3/commentThreads` +
    `?part=snippet&videoId=${videoId}&maxResults=${maxResults}&order=relevance&key=${YOUTUBE_API_KEY}`;
  const data = await httpsGet(url);
  if (data.error) {
    // Comments may be disabled on the video
    if (data.error.errors?.[0]?.reason === 'commentsDisabled') return [];
    throw new Error(`YouTube API: ${data.error.message}`);
  }
  return (data.items || []).map(
    (item) => item.snippet.topLevelComment.snippet.textDisplay
  );
}

async function analyzeComments(videos) {
  const client = new Anthropic({ apiKey: ANTHROPIC_API_KEY });

  const dump = videos
    .map(
      (v) =>
        `### "${v.title}" (${v.publishedAt.slice(0, 10)})\n` +
        v.comments.map((c, i) => `${i + 1}. ${c}`).join('\n')
    )
    .join('\n\n');

  const msg = await client.messages.create({
    model: 'claude-sonnet-5',
    max_tokens: 1200,
    messages: [
      {
        role: 'user',
        content:
          `You are analyzing YouTube comments for a hot sauce brand called "Eruption Hot Sauce".\n` +
          `Based on the comments below, write a concise report with exactly these sections:\n\n` +
          `**Overall Sentiment** — one-sentence summary plus rough % positive/neutral/negative\n` +
          `**What Viewers Love** — up to 5 bullet points\n` +
          `**Improvement Suggestions** — up to 5 specific, actionable bullet points from viewer feedback\n` +
          `**Recurring Complaints** — up to 3 bullet points (skip section if none)\n` +
          `**Recommended Next Steps** — up to 3 concrete ideas for future videos or content\n\n` +
          `Be direct and specific. Avoid filler phrases.\n\n${dump}`,
      },
    ],
  });

  return msg.content[0].text;
}

function buildHtml(analysis, videos, totalComments) {
  const date = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  const videoList = videos
    .map(
      (v) =>
        `<li><strong>${v.title}</strong> — ${v.comments.length} comment${v.comments.length !== 1 ? 's' : ''}</li>`
    )
    .join('');

  const analysisHtml = analysis
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');

  return `
<!DOCTYPE html>
<html>
<body style="font-family: Georgia, serif; max-width: 680px; margin: 0 auto; color: #1a1a1a; line-height: 1.6;">
  <h1 style="font-size: 22px; border-bottom: 3px solid #e05a00; padding-bottom: 8px;">
    🌋 Eruption Hot Sauce — YouTube Weekly Digest
  </h1>
  <p style="color: #555; font-size: 14px;">${date} · ${videos.length} video${videos.length !== 1 ? 's' : ''} · ${totalComments} comment${totalComments !== 1 ? 's' : ''} analyzed</p>

  <h2 style="font-size: 16px; margin-top: 24px;">Videos covered</h2>
  <ul style="font-size: 14px;">${videoList}</ul>

  <h2 style="font-size: 16px; margin-top: 24px;">Analysis</h2>
  <div style="font-size: 15px;">${analysisHtml}</div>

  <hr style="margin-top: 40px; border: none; border-top: 1px solid #ddd;">
  <p style="color: #888; font-size: 12px;">
    Generated automatically by the Eruption Hot Sauce YouTube routine.<br>
    To update or disable, edit <code>.github/workflows/youtube-summary.yml</code>.
  </p>
</body>
</html>`;
}

async function main() {
  const missing = [
    'YOUTUBE_API_KEY',
    'YOUTUBE_CHANNEL_ID',
    'ANTHROPIC_API_KEY',
    'GMAIL_USER',
    'GMAIL_APP_PASSWORD',
  ].filter((k) => !process.env[k]);

  if (missing.length) {
    console.error(`Missing required env vars: ${missing.join(', ')}`);
    process.exit(1);
  }

  console.log('Fetching uploads playlist...');
  const uploadsPlaylistId = await getUploadsPlaylistId();

  console.log('Fetching recent videos...');
  const videos = await getRecentVideos(uploadsPlaylistId, 10);
  console.log(`Found ${videos.length} videos.`);

  console.log('Fetching comments...');
  for (const video of videos) {
    video.comments = await getComments(video.id, 100);
    console.log(`  "${video.title}": ${video.comments.length} comments`);
  }

  const withComments = videos.filter((v) => v.comments.length > 0);
  const totalComments = withComments.reduce((n, v) => n + v.comments.length, 0);

  if (totalComments === 0) {
    console.log('No comments found on any recent video. Skipping email.');
    return;
  }

  console.log(`Analyzing ${totalComments} comments with Claude...`);
  const analysis = await analyzeComments(withComments);

  console.log('Sending email...');
  const transporter = nodemailer.createTransport({
    service: 'gmail',
    auth: { user: GMAIL_USER, pass: GMAIL_APP_PASSWORD },
  });

  const date = new Date().toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });

  await transporter.sendMail({
    from: `"Eruption Routine" <${GMAIL_USER}>`,
    to: RECIPIENT_EMAIL || GMAIL_USER,
    subject: `YouTube Comment Summary — ${date}`,
    html: buildHtml(analysis, withComments, totalComments),
  });

  console.log('Done. Email sent to', RECIPIENT_EMAIL || GMAIL_USER);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
