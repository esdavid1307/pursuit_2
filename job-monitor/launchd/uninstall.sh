#!/bin/bash
# Remove the launchd user agents installed by install.sh.
set -euo pipefail

AGENTS="$HOME/Library/LaunchAgents"
for name in com.pursuit.job-monitor com.pursuit.catalog-refresh; do
    launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
    rm -f "$AGENTS/$name.plist"
    echo "Removed $name"
done
