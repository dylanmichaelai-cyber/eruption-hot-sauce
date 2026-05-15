#!/usr/bin/env bash
# YouTube Comment Summary Routine
# Run manually or schedule with cron:
#   0 9 * * 1  /path/to/run_summary.sh   (every Monday at 9am)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if it exists
if [ -f "$SCRIPT_DIR/../.env" ]; then
  set -a
  source "$SCRIPT_DIR/../.env"
  set +a
fi

echo "=== YouTube Summary Routine ==="
echo "Step 1: Fetching YouTube comments..."
python3 "$SCRIPT_DIR/fetch_youtube_comments.py"

echo ""
echo "Step 2: Analyzing and emailing..."
python3 "$SCRIPT_DIR/analyze_and_email.py"

echo ""
echo "Done."
