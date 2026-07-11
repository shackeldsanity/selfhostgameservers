#!/usr/bin/env python3
"""
Provably-fair game-server watcher (multi-game).

Runs on the game host. Discovers every game under games/<name>/manifest.json
(folders starting with '_' are ignored) and, each cycle, for each game:
  - hashes the live config and compares it to the game's approved hash,
  - verifies the admin locks are OFF (manifest 'runtime_forbidden' rules),
  - scans the container logs for forbidden admin activity ('log_forbidden'),
  - writes heartbeat/<name>.json and (periodically) pushes them to GitHub so the
    off-host GitHub Action can confirm each server is alive and unmodified.

Any drift or admin activity is posted to Discord immediately.

Usage:
  python3 watcher.py                 # watch loop over ALL games
  python3 watcher.py --approve       # record approved hash for ALL games, then exit
  python3 watcher.py --approve NAME  # record approved hash for one game, then exit
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def load_env(path):
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


CFG = {**load_env(Path(__file__).with_name("watcher.env")), **os.environ}
REPO_DIR = CFG.get("REPO_DIR", str(Path(__file__).resolve().parents[1]))
WEBHOOK = CFG.get("DISCORD_WEBHOOK_URL", "")
CHECK_INTERVAL = int(CFG.get("CHECK_INTERVAL", "60"))
PUSH_INTERVAL = int(CFG.get("PUSH_INTERVAL", "300"))
HEARTBEAT_PUSH = CFG.get("HEARTBEAT_PUSH", "false").lower() == "true"
GIT_REMOTE = CFG.get("GIT_REMOTE", "origin")
# Heartbeats push to their own branch/checkout so `main` can be branch-protected.
HEARTBEAT_REPO = CFG.get("HEARTBEAT_REPO", REPO_DIR)
HEARTBEAT_BRANCH = CFG.get("HEARTBEAT_BRANCH", "main")


def sh(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception as e:
        print(f"cmd failed {args}: {e}")
        return ""


def discover_games():
    games = []
    for mpath in sorted(glob.glob(os.path.join(REPO_DIR, "games", "*", "manifest.json"))):
        if os.path.basename(os.path.dirname(mpath)).startswith("_"):
            continue
        try:
            games.append(json.loads(Path(mpath).read_text()))
        except Exception as e:
            print(f"bad manifest {mpath}: {e}")
    return games


def live_config_path(m):
    return os.path.join(REPO_DIR, m["compose_dir"], m["live_config"])


def approved_path(m):
    return os.path.join(REPO_DIR, m["compose_dir"], "config", "approved.sha256")


def read_text(p):
    try:
        return Path(p).read_text(errors="replace")
    except FileNotFoundError:
        return None


def sha256(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest() if text is not None else None


def read_approved(m):
    try:
        for line in Path(approved_path(m)).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except FileNotFoundError:
        pass
    return None


def runtime_violations(m, text):
    return [r["message"] for r in m.get("runtime_forbidden", []) if re.search(r["pattern"], text, re.I)]


def log_violations(m):
    logs = sh(["docker", "logs", "--since", "120s", m["container"]])
    return [r["message"] for r in m.get("log_forbidden", []) if re.search(r["pattern"], logs, re.I)]


def image_digest(container):
    return sh(["docker", "inspect", "--format", "{{.Image}}", container]) or "unknown"


def git_commit():
    return sh(["git", "-C", REPO_DIR, "rev-parse", "--short", "HEAD"]) or "unknown"


def discord(title, lines):
    if not WEBHOOK:
        print(f"[no webhook] {title}: {lines}")
        return
    desc = "\n".join(f"• {l}" for l in lines) if isinstance(lines, list) else str(lines)
    payload = {"embeds": [{"title": title, "description": desc, "color": 0xE01E1E}]}
    try:
        req = urllib.request.Request(
            WEBHOOK, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "RageQuit-Iris/1.0"}
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"discord post failed: {e}")


def heartbeat_path(name):
    return os.path.join(HEARTBEAT_REPO, "heartbeat", f"{name}.json")


def write_heartbeat(m, status, live_hash, approved):
    hp = heartbeat_path(m["name"])
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    hb = {
        "game": m["name"],
        "ts": int(time.time()),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "runtime_config_sha256": live_hash,
        "approved_config_sha256": approved,
        "image": image_digest(m["container"]),
        "git_commit": git_commit(),
    }
    Path(hp).write_text(json.dumps(hb, indent=2) + "\n")


def push_heartbeats():
    sh(["git", "-C", HEARTBEAT_REPO, "add", "heartbeat"])
    sh(["git", "-C", HEARTBEAT_REPO, "commit", "-m", "heartbeat", "--no-verify"])
    sh(["git", "-C", HEARTBEAT_REPO, "push", GIT_REMOTE, HEARTBEAT_BRANCH])


def approve(one=None):
    found = False
    for m in discover_games():
        if one and m["name"] != one:
            continue
        found = True
        text = read_text(live_config_path(m))
        if text is None:
            print(f"[{m['name']}] live config not found at {live_config_path(m)} — start it first.")
            continue
        h = sha256(text)
        ap = approved_path(m)
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        Path(ap).write_text(h + "\n")
        print(f"[{m['name']}] approved {h}\n  wrote {ap} — commit it.")
    if one and not found:
        print(f"No game named '{one}' found under games/.")


def main():
    if "--approve" in sys.argv:
        i = sys.argv.index("--approve")
        approve(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
        return

    print("watcher: starting (multi-game)")
    last_alert = {}  # name -> last-alerted config hash (dedupe)
    last_push = 0.0
    while True:
        for m in discover_games():
            text = read_text(live_config_path(m))
            live_hash = sha256(text)
            approved = read_approved(m)
            problems = []
            status = "ok"

            if text is None:
                problems.append("live config not found — server may be down")
                status = "config-missing"
            else:
                problems += runtime_violations(m, text)
                problems += log_violations(m)
                if approved and approved != "REPLACE_AFTER_FIRST_DEPLOY" and live_hash != approved:
                    problems.append(f"config DRIFT: live {live_hash[:12]} != approved {approved[:12]}")
                if problems:
                    status = "violation"

            if problems and last_alert.get(m["name"]) != live_hash:
                discord(f"⚠️ {m.get('display_name', m['name'])} integrity alert", problems)
                last_alert[m["name"]] = live_hash

            write_heartbeat(m, status, live_hash, approved)

        now = time.time()
        if HEARTBEAT_PUSH and now - last_push >= PUSH_INTERVAL:
            push_heartbeats()
            last_push = now

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
