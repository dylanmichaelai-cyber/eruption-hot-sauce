#!/usr/bin/env bash
# Adds a weekly cron job that runs the digest every Monday at 08:00.
# Run once: bash cron-setup.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(which python3)"
LOG="$SCRIPT_DIR/digest.log"

CRON_LINE="0 8 * * 1 cd \"$SCRIPT_DIR\" && $PYTHON digest.py >> \"$LOG\" 2>&1"

# Add if not already present
( crontab -l 2>/dev/null | grep -qF "digest.py" ) \
  && echo "Cron job already exists — skipping." \
  || ( crontab -l 2>/dev/null; echo "$CRON_LINE" ) | crontab -

echo "Cron job scheduled:"
echo "  $CRON_LINE"
echo ""
echo "To run manually:   cd $SCRIPT_DIR && python3 digest.py"
echo "To view logs:      tail -f $LOG"
echo "To edit schedule:  crontab -e"
