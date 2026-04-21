#!/usr/bin/env bash
# Wrapper that loads .env and runs the summary script.
# Usage: ./run_summary.sh
# Schedule via cron: 0 9 * * 1 /path/to/run_summary.sh >> /tmp/yt_summary.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env if it exists
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env"
  set +a
fi

# Activate virtual environment if present
if [[ -f "$SCRIPT_DIR/venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/venv/bin/activate"
fi

python "$SCRIPT_DIR/youtube_summary.py"
