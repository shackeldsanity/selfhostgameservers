#!/usr/bin/env bash
# Run INSIDE the Ubuntu VM after first boot. Installs Docker + prerequisites,
# enables the firewall (SSH here — per-game ports are opened by deploy.sh from
# each game's manifest), clones this repo, and prepares the watcher user.
# Safe to re-run. Works as a normal sudo user or when invoked as root by cloud-init.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ShackledSanity/selfhostgameservers.git}"
REPO_DIR=/opt/selfhostgameservers

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
LOGIN_USER="${SUDO_USER:-${USER:-ubuntu}}"

echo "==> System update + prerequisites"
$SUDO apt-get update
$SUDO apt-get install -y ca-certificates curl git python3 ufw qemu-guest-agent

echo "==> Docker Engine + Compose plugin (official Docker repo)"
$SUDO install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
$SUDO chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
$SUDO apt-get update
$SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
$SUDO systemctl enable --now docker qemu-guest-agent

echo "==> Firewall: allow SSH (deploy.sh opens each game's ports from its manifest)"
$SUDO ufw allow OpenSSH
$SUDO ufw --force enable

echo "==> Clone repo to $REPO_DIR"
$SUDO mkdir -p "$REPO_DIR"
$SUDO chown "$LOGIN_USER":"$LOGIN_USER" "$REPO_DIR"
[ -d "$REPO_DIR/.git" ] || git clone "$REPO_URL" "$REPO_DIR"

echo "==> Dedicated watcher user (docker access, no login shell)"
id gameservers-watcher &>/dev/null || $SUDO useradd --system --home "$REPO_DIR" --shell /usr/sbin/nologin gameservers-watcher
$SUDO usermod -aG docker gameservers-watcher
$SUDO usermod -aG docker "$LOGIN_USER"

cat <<EOF

✅ VM prepared. Next (inside $REPO_DIR):
  1) Pin each game's image digest, e.g. for Palworld in games/palworld/stack.env:
       docker buildx imagetools inspect thijsvanloef/palworld-server-docker:v0.42.0
  2) ./scripts/deploy.sh                 # deploy all games (or: ./scripts/deploy.sh palworld)
  3) python3 watcher/watcher.py --approve && git add games/*/config/approved.sha256 && git commit -m approve && git push
  4) cp watcher/watcher.env.example watcher/watcher.env   # fill webhook + git push creds
  5) $SUDO cp watcher/gameservers-watcher.service /etc/systemd/system/ && $SUDO systemctl enable --now gameservers-watcher

Log out/in first so your docker group membership applies.
Then port-forward each game's ports (e.g. Palworld 8211/udp) on your router to this VM's IP.
EOF
