#!/bin/bash
# One-shot VM setup for the internship monitor (Debian/Ubuntu).
# Run as your normal login user (needs sudo): bash deploy/setup.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

if [ ! -f "$REPO/job-monitor/.env" ]; then
    echo "Missing $REPO/job-monitor/.env (it holds your Discord webhook)." >&2
    echo "Copy it from your Mac first, e.g.:" >&2
    echo "  scp ~/Desktop/pursuit_2/job-monitor/.env $USER_NAME@<vm-ip>:$REPO/job-monitor/.env" >&2
    exit 1
fi

sudo apt-get update -y
sudo apt-get install -y git python3 python3-venv python3-pip

python3 -m venv "$REPO/job-monitor/.venv"
"$REPO/job-monitor/.venv/bin/pip" install --quiet -r "$REPO/job-monitor/requirements.txt"

if [ ! -f "$REPO/companies.json" ]; then
    echo "Building company catalog (first run mines the source repos; this can take a while)..."
    (cd "$REPO" && python3 main.py && python3 main.py --export)
fi

for unit in job-monitor.service catalog-refresh.service catalog-refresh.timer; do
    sed -e "s|__REPO__|$REPO|g" -e "s|__USER__|$USER_NAME|g" "$REPO/deploy/$unit" \
        | sudo tee "/etc/systemd/system/$unit" >/dev/null
done

# Let the refresh job restart the monitor without a password prompt.
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart job-monitor" \
    | sudo tee /etc/sudoers.d/job-monitor-refresh >/dev/null
sudo chmod 440 /etc/sudoers.d/job-monitor-refresh

sudo systemctl daemon-reload
sudo systemctl enable --now job-monitor.service catalog-refresh.timer

echo
echo "Done. Check it with:"
echo "  systemctl status job-monitor"
echo "  journalctl -u job-monitor -f"
