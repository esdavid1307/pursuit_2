#!/bin/bash
# Daily VM job: pull latest code, rebuild the company catalog, restart the
# monitor so it re-imports targets (and picks up any code updates).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

git pull --ff-only || true
python3 main.py
python3 main.py --export

sudo systemctl restart job-monitor
