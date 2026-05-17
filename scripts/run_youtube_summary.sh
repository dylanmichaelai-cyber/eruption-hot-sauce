#!/usr/bin/env bash
# Runs the YouTube comment summary and emails the results.
# Schedule with cron — example (every Monday at 8 AM):
#   0 8 * * 1 /path/to/eruption-hot-sauce/scripts/run_youtube_summary.sh >> /tmp/yt_summary.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
python3 "$SCRIPT_DIR/youtube_summary.py"
