#!/usr/bin/env bash
# Run the YouTube comment analysis report.
# Usage: ./run_comment_report.sh
#
# Schedule weekly with cron (every Monday at 8 AM):
#   0 8 * * 1 /home/user/eruption-hot-sauce/run_comment_report.sh >> /home/user/eruption-hot-sauce/report.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

cd "$SCRIPT_DIR"
exec python3 youtube_comment_report.py
