#!/usr/bin/env bash
# Cron wrapper: activate the virtualenv, run one incremental ingest, append to the log.
# The pipeline holds its own lock, so overlapping cron fires exit cleanly.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

mkdir -p logs
python -m battery_dash.ingest.pipeline "$@" >> logs/cron.log 2>&1
