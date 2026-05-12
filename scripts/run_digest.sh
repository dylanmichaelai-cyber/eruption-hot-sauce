#!/usr/bin/env bash
# Run the YouTube comment digest.
# Usage: ./run_digest.sh
#        or schedule via cron (see below)
#
# Cron example — every Monday at 9 AM:
#   0 9 * * 1 /path/to/eruption-hot-sauce/scripts/run_digest.sh >> /tmp/yt_digest.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy .env.example to .env and fill in your values."
  exit 1
fi

# Load env vars
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

python3 "$SCRIPT_DIR/youtube_digest.py"
