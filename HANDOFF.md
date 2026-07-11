# Handoff — provision the provably-fair Palworld VM on Proxmox

Paste everything below into the Claude session connected to the Proxmox host. The
repo URL and my SSH key are already filled in.

---

You are connected to a **Proxmox VE host**. Set up a dedicated **Ubuntu 24.04 VM**
to host our game servers (a multi-game host — Palworld first), following the repo at `https://github.com/shackeldsanity/selfhostgameservers.git`.

**Do NOT install anything game-related on the Proxmox host OS itself** — everything
runs inside the VM. This host has root; be deliberate.

## Ground rules
- **Verify before you create.** Never overwrite an existing VM.
- After you've gathered the facts, **print the final plan (VMID, storage, bridge,
  cores, RAM, disk) and STOP for my confirmation** before running `qm create`.

## 1. Discover the environment and report back
```bash
pveversion                 # needs 7.2+ for the 'import-from' disk syntax
qm list                    # choose an UNUSED VMID (target 110; change if taken)
pvesm status               # confirm the VM-disk storage name (local-lvm? local-zfs?)
ip -br link | grep -i vmbr # confirm the bridge (usually vmbr0)
```

## 2. Get the scripts
```bash
git clone https://github.com/shackeldsanity/selfhostgameservers.git /root/selfhostgameservers
cd /root/selfhostgameservers
```
(If the repo isn't on GitHub yet, ask me to paste `proxmox/create-vm.sh`.)

## 3. Install my SSH key
Write MY SSH public key to `/root/id_ed25519.pub` — I will paste it here when I
run this (it is deliberately NOT stored in the repo). This is the key I'll use to
log into the VM.

## 4. Configure + review `proxmox/create-vm.sh`
Edit the variable block at the top using what you found in step 1 (VMID, STORAGE,
BRIDGE, MEMORY, DISK_SIZE, SSH_KEYFILE=/root/id_ed25519.pub). **Print the final
block and wait for my OK.**

## 5. Create the VM
```bash
bash proxmox/create-vm.sh
sleep 90
qm guest cmd <VMID> network-get-interfaces   # get the VM's IP once the agent is up
```

## 6. Bootstrap inside the VM
SSH in (`ssh ubuntu@<vm-ip>`) — or use `qm guest exec`. The repo is NOT on the VM
yet, so fetch the bootstrap script first; it installs Docker + git and clones the
repo to /opt itself:
```bash
sudo apt-get update && sudo apt-get install -y curl
curl -fsSL https://raw.githubusercontent.com/shackeldsanity/selfhostgameservers/main/proxmox/bootstrap-vm.sh -o /tmp/bootstrap-vm.sh
cat /tmp/bootstrap-vm.sh    # optional: review before running
REPO_URL=https://github.com/shackeldsanity/selfhostgameservers.git bash /tmp/bootstrap-vm.sh
```

## 7. Deploy (inside the VM, in /opt/selfhostgameservers)
```bash
docker buildx imagetools inspect thijsvanloef/palworld-server-docker:v0.42.0
# paste the sha256 into PALWORLD_IMAGE in games/palworld/stack.env, commit it, then:
./scripts/deploy.sh
python3 watcher/watcher.py --approve   # then commit games/palworld/config/approved.sha256
```
I will provide the Discord webhook + GitHub push credentials for
`watcher/watcher.env` and the systemd watcher — ask me for them at this step.

## 8. Report back
Tell me: the VMID, the VM's IP, `docker ps` status, and **confirm RCONEnabled and
RESTAPIEnabled are False and AdminPassword is empty** in the running
`PalWorldSettings.ini`. Then remind me to port-forward `8211/udp` to the VM.

---
