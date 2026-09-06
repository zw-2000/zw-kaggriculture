#!/bin/bash
# Append the live rating of every submission to a timestamped log. Ratings start
# at 600.0 and climb as episodes play, so a single reading is not a result --
# the trajectory is. See FINDINGS 12.9.
set -euo pipefail
cd "$(dirname "$0")"
LOG=live_scores.tsv
[ -f $LOG ] || printf 'utc\tref\tsubmitted\tscore\n' > $LOG
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
timeout 120 .venv/bin/kaggle competitions submissions kaggriculture -v \
  | tail -n +2 | awk -F',' -v t="$NOW" \
      'NF>3 && $NF-1 != "" {print t"\t"$1"\t"$3"\t"$(NF-1)}' >> $LOG
awk -F'\t' -v t="$NOW" '$1 == t' $LOG | head -6
