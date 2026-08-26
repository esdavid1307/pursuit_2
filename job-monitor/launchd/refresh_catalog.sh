#!/bin/bash
# Refresh companies.json from the discovery pipeline, then restart the monitor
# so it re-imports targets and starts polling any newly discovered boards.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

/usr/bin/python3 main.py
/usr/bin/python3 main.py --export

launchctl kickstart -k "gui/$(id -u)/com.pursuit.job-monitor" || true
