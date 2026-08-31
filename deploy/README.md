# Run the monitor 24/7 on a Linux VM

Any small Debian/Ubuntu VM works. Free/cheap options:

- **Oracle Cloud "Always Free"** — permanently free ARM VM (oracle.com/cloud/free). Most setup friction, $0 forever.
- **Hetzner Cloud** — ~€4/mo CX22, simplest signup (hetzner.com/cloud).
- **DigitalOcean** — ~$4-6/mo basic droplet.

Pick Ubuntu 22.04 or newer when creating the VM and add your SSH key.

## Deploy

```bash
# 1. On the VM: clone the repo
ssh <user>@<vm-ip>
git clone https://github.com/esdavid1307/pursuit_2.git
exit

# 2. From your Mac: copy the secrets (never committed to git)
scp ~/Desktop/pursuit_2/.env <user>@<vm-ip>:pursuit_2/.env

# 3. On the VM: run setup
ssh <user>@<vm-ip>
bash pursuit_2/deploy/setup.sh
```

`setup.sh` installs Python, builds the virtualenv, mines the company catalog
(first run takes a while), installs two systemd units, and starts them:

- `job-monitor.service` — the monitor, auto-restarts on crash and on reboot.
- `catalog-refresh.timer` — every 4 hours: `git pull`, rebuild `data/companies.json`,
  restart the monitor so new companies/code are picked up.

## Verify and manage

```bash
systemctl status job-monitor            # should be active (running)
journalctl -u job-monitor -f            # live scan log
systemctl list-timers catalog-refresh*  # next refresh time
sudo systemctl restart job-monitor      # manual restart
```

