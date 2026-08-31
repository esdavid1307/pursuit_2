#!/bin/bash
# VM job (every 4 hours): pull latest code, rebuild the company catalog,
# restart the monitor so it re-imports targets (and picks up code updates).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

git pull --ff-only || true
.venv/bin/python -m catalog
.venv/bin/python -m catalog --export

sudo systemctl restart job-monitor
