#!/usr/bin/env bash
# Fetches recent YouTube comments for the Eruption Hot Sauce channel.
# Outputs a plain-text report to stdout.
#
# Usage:
#   ./scripts/youtube-summary.sh
#   YOUTUBE_API_KEY=xxx ./scripts/youtube-summary.sh "my channel name"

set -euo pipefail

API_KEY="${YOUTUBE_API_KEY:-AIzaSyDrPa11MXDW3V6A6HU3_mPt7klQjJp5T8c}"
CHANNEL_QUERY="${1:-eruption hot sauce}"
MAX_VIDEOS=10
MAX_COMMENTS=50
BASE_URL="https://www.googleapis.com/youtube/v3"

echo "=== YouTube Comments Report ==="
echo "Date: $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "Channel search: '${CHANNEL_QUERY}'"
echo ""

# ── 1. Find channel ────────────────────────────────────────────────────────────
ENCODED_QUERY=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CHANNEL_QUERY")
SEARCH_RESP=$(curl -sf "${BASE_URL}/search?part=snippet&q=${ENCODED_QUERY}&type=channel&maxResults=5&key=${API_KEY}" || true)

CHANNEL_ID=$(echo "$SEARCH_RESP" | jq -r '.items[0].id.channelId // empty' 2>/dev/null)
CHANNEL_NAME=$(echo "$SEARCH_RESP" | jq -r '.items[0].snippet.channelTitle // empty' 2>/dev/null)

if [ -z "$CHANNEL_ID" ]; then
  echo "ERROR: Channel not found. Response:"
  echo "$SEARCH_RESP"
  exit 1
fi

echo "Channel : ${CHANNEL_NAME}"
echo "ID      : ${CHANNEL_ID}"

# ── 2. Get channel stats + uploads playlist ────────────────────────────────────
CHANNEL_RESP=$(curl -sf "${BASE_URL}/channels?part=contentDetails,statistics&id=${CHANNEL_ID}&key=${API_KEY}")
UPLOADS_PLAYLIST=$(echo "$CHANNEL_RESP" | jq -r '.items[0].contentDetails.relatedPlaylists.uploads')
SUBSCRIBER_COUNT=$(echo "$CHANNEL_RESP" | jq -r '.items[0].statistics.subscriberCount // "hidden"')
VIDEO_COUNT=$(echo "$CHANNEL_RESP"      | jq -r '.items[0].statistics.videoCount      // "unknown"')

echo "Subscribers: ${SUBSCRIBER_COUNT}"
echo "Total videos: ${VIDEO_COUNT}"
echo ""

# ── 3. Get recent videos ───────────────────────────────────────────────────────
PLAYLIST_RESP=$(curl -sf "${BASE_URL}/playlistItems?part=snippet&playlistId=${UPLOADS_PLAYLIST}&maxResults=${MAX_VIDEOS}&key=${API_KEY}")
VIDEOS=$(echo "$PLAYLIST_RESP" | jq -r '.items[] | [.snippet.resourceId.videoId, .snippet.title] | @tsv')

if [ -z "$VIDEOS" ]; then
  echo "ERROR: No videos found in uploads playlist"
  exit 1
fi

# ── 4. Fetch comments for each video ──────────────────────────────────────────
TOTAL_COMMENTS=0

while IFS=$'\t' read -r VIDEO_ID VIDEO_TITLE; do
  [ -z "$VIDEO_ID" ] && continue

  echo "=== ${VIDEO_TITLE}"
  echo "    https://www.youtube.com/watch?v=${VIDEO_ID}"

  COMMENTS_RESP=$(curl -sf \
    "${BASE_URL}/commentThreads?part=snippet&videoId=${VIDEO_ID}&maxResults=${MAX_COMMENTS}&order=relevance&key=${API_KEY}" \
    || echo '{"items":[]}')

  # Comments disabled or error
  ERROR_REASON=$(echo "$COMMENTS_RESP" | jq -r '.error.errors[0].reason // empty')
  if [ -n "$ERROR_REASON" ]; then
    echo "    [comments disabled or unavailable]"
    echo ""
    continue
  fi

  COUNT=$(echo "$COMMENTS_RESP" | jq '.items | length')
  echo "    ${COUNT} comment(s)"
  echo ""

  echo "$COMMENTS_RESP" | jq -r '
    .items[] |
    "  [\(.snippet.topLevelComment.snippet.likeCount // 0) likes] " +
    "\(.snippet.topLevelComment.snippet.authorDisplayName): " +
    "\(.snippet.topLevelComment.snippet.textDisplay | gsub("\n";" "))"
  '

  echo ""
  TOTAL_COMMENTS=$((TOTAL_COMMENTS + COUNT))

done <<< "$VIDEOS"

echo "==============================="
echo "Total comments fetched: ${TOTAL_COMMENTS}"
