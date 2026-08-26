#!/bin/bash
# Install the job monitor and daily catalog refresh as launchd user agents.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$REPO/job-monitor/logs"

for name in com.pursuit.job-monitor com.pursuit.catalog-refresh; do
    sed "s|__REPO__|$REPO|g" "$REPO/job-monitor/launchd/$name.plist.template" > "$AGENTS/$name.plist"
    launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
    tries=0
    until launchctl bootstrap "gui/$(id -u)" "$AGENTS/$name.plist" 2>/dev/null; do
        tries=$((tries + 1))
        if [ "$tries" -ge 10 ]; then
            echo "Failed to bootstrap $name" >&2
            exit 1
        fi
        sleep 2
    done
    echo "Installed $name"
done

echo "Verify with: launchctl print gui/$(id -u)/com.pursuit.job-monitor | head"
echo "Logs: tail -f $REPO/job-monitor/logs/monitor.out.log"
