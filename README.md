# Provably-fair game-server host

A self-hosted, multi-game server host (on Proxmox) that you can **play on as a
normal player** while giving everyone confidence that **no one — including you,
the host — can use admin commands or quietly change settings** without it being
detected, announced, and permanently recorded.

**Palworld** is the first game; the repo is structured so more games drop in as
self-contained modules under [`games/`](games/). One shared Ubuntu VM runs each
game as its own container.

It costs **$0**: Docker + a public GitHub repo + a Discord webhook + free GitHub
Actions. No paid VPS.

## The idea in one paragraph

You own the box, so you have root — pure "you *can't* cheat" is impossible while
self-hosting. So instead we make cheating **detectable and public**:

1. **Lock it down** — each game disables its entire admin surface (for Palworld:
   `AdminPassword`, `RCON`, `REST API`). A GitHub Action *fails the build* if any
   commit tries to re-enable admin for any game.
2. **Publish the truth** — every setting lives in this public repo as
   config-as-code. Changing anything is a public, signed commit.
3. **Continuously prove nothing changed** — a watcher on the VM hashes every
   game's live config every 60s, alerts Discord on any drift or admin activity,
   and pushes a per-game **heartbeat** to GitHub. A scheduled GitHub Action
   (running off your host) checks each heartbeat is fresh and matches the approved
   config — if a server goes silent or drifts, it alerts everyone.

See **[TRUST.md](TRUST.md)** for the player-facing explanation and honest limits,
and **[games/README.md](games/README.md)** for how to add a game.

## Layout

| Path | What it is |
|---|---|
| `proxmox/create-vm.sh` | Runs on the Proxmox host — provisions the Ubuntu VM |
| `proxmox/bootstrap-vm.sh` | Runs in the VM — installs Docker, firewall, clones repo |
| `games/<name>/` | One self-contained game module (compose, config, admin locks, manifest) |
| `games/_template/` | Skeleton to copy when adding a game |
| `watcher/watcher.py` | The shared watcher — loops over every game (hash + log scan + Discord + heartbeat) |
| `scripts/deploy.sh` | Deploys all games (or one by name); opens each game's firewall ports |
| `heartbeat/<name>.json` | Latest signed heartbeat, one per game |
| `.github/workflows/audit-config.yml` | Off-host: proves every game's published config is admin-free |
| `.github/workflows/heartbeat-check.yml` | Off-host: proves every live server is fresh + unmodified |

## Setup

**1. Publish this repo (public) on GitHub.** In repo *Settings → Secrets and
variables → Actions*, add secret `DISCORD_WEBHOOK_URL`. Turn on branch protection
for `main` (require PR review — ideally from a neutral player — and disallow force
pushes) so config changes can't be sneaked in.

**2. Provision the Ubuntu VM on Proxmox.** The game servers run in a dedicated
Ubuntu 24.04 VM — **not** on the Proxmox host OS. On the Proxmox node shell (as
root), edit the variables at the top of [`proxmox/create-vm.sh`](proxmox/create-vm.sh)
(VM id, cores, RAM, storage, your SSH public key), then run it:

```bash
bash proxmox/create-vm.sh                 # creates + starts the cloud-init VM
qm guest cmd 110 network-get-interfaces   # find the VM's IP (once the agent is up)
```

VM sizing — one shared VM hosts every game, so size for the sum. Palworld alone
(RAM is the constraint): ~8 GB for ≤8 players, 12 GB for ≤16, 16 GB for ≤32. Add
headroom per extra game.

**3. Bootstrap the VM.** SSH in and run the bootstrap — it installs Docker, enables
the firewall (SSH), and clones this repo. The repo isn't on the VM yet, so fetch
the script first (it does the cloning):

```bash
ssh ubuntu@<vm-ip>
sudo apt-get update && sudo apt-get install -y curl
curl -fsSL https://raw.githubusercontent.com/ShackledSanity/selfhostgameservers/main/proxmox/bootstrap-vm.sh -o /tmp/bootstrap-vm.sh
REPO_URL=https://github.com/ShackledSanity/selfhostgameservers.git bash /tmp/bootstrap-vm.sh
```

(Prefer zero-touch? Use [`proxmox/cloud-init-user-data.yaml`](proxmox/cloud-init-user-data.yaml)
as a cloud-init snippet and steps 2–3 happen automatically on first boot.)

**4. Deploy** (inside the VM). Pin each game's image digest first:

```bash
cd /opt/selfhostgameservers
docker buildx imagetools inspect thijsvanloef/palworld-server-docker:v0.42.0
# paste the sha256 into PALWORLD_IMAGE in games/palworld/stack.env, commit it, then:
./scripts/deploy.sh            # all games  (or: ./scripts/deploy.sh palworld)
```

**5. Record the approved config** once each server has generated its config:

```bash
python3 watcher/watcher.py --approve         # approves every game (or: --approve palworld)
git add games/*/config/approved.sha256 && git commit -m "approve initial config" && git push
```

**6. Start the watcher:**

```bash
cp watcher/watcher.env.example watcher/watcher.env   # fill in webhook + git push creds
sudo cp watcher/gameservers-watcher.service /etc/systemd/system/
sudo systemctl enable --now gameservers-watcher
```

Finally, **port-forward each game's ports** (Palworld: `8211/udp`, plus
`27015/udp` for the community browser) on your router to the VM's IP, and give the
VM a static IP or DHCP reservation so the forward stays valid.

That's it. The audit + heartbeat Actions run automatically.

## Changing a setting (the only correct way)

1. Open a pull request editing `games/<game>/game.env` (or `stack.env`).
2. `audit-config` runs — it blocks the merge if the change re-enables admin.
3. Merge, then on the VM: `./scripts/deploy.sh <game>`.
4. `python3 watcher/watcher.py --approve <game>` and commit the new `approved.sha256`.

Any change made *outside* this flow — editing a file on the box directly — shows
up as config drift and fires an alert within a minute.

## Adding a game

`cp -r games/_template games/<name>`, fill in its `manifest.json`, `docker-compose.yml`,
`game.env`, and `stack.env`, then follow steps 4–6 for that game. Full field
reference in [games/README.md](games/README.md).

## Hardening later (optional, still free)

- Move heartbeat pushes to a dedicated `heartbeat` branch to keep `main` clean.
- Have a **neutral player** hold the `DISCORD_WEBHOOK_URL` secret and own branch
  protection — that closes the last gap described in TRUST.md.
