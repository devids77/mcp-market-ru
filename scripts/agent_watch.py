#!/usr/bin/env python3
"""Watch nginx access logs for real MCP agent traffic.

Run every 30 min via cron. Notifies Telegram on first sighting of new (IP, UA)
pair posting to /mcp/.

Usage:
  python3 agent_watch.py            # default mode: scan + alert on new
  python3 agent_watch.py --seed     # initial run: seed state, no alerts
  python3 agent_watch.py --dry-run  # show what would be alerted, no send/state
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

NGINX_LOG = "/var/log/nginx/access.log"
ROOT = Path("/opt/mcp-market")
SIGHTINGS_FILE = ROOT / "data" / "agent_sightings.jsonl"
SEEN_FILE = ROOT / "data" / "agent_seen.json"

AGENT_PATTERNS = re.compile(
    r"(?i)claude|cursor|cline|continue|windsurf|copilot|anthropic|openai|mcp[/-]|fastmcp|httpx"
)
SKIP_PATTERNS = re.compile(
    r"(?i)mozilla|chrome|safari|firefox|edge|opera|bot|spider|monitor|uptime|"
    r"pingdom|googlebot|bingbot|yandexbot|curl|wget|python-urllib|python-requests/2|"
    r"nikto|nmap|masscan|zgrab|sentry|datadog|newrelic"
)
LINE_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) '
    r'\S+" (?P<status>\d+) \S+ "[^"]*" "(?P<ua>[^"]*)"'
)


def load_seen() -> dict:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text())
    return {}


def save_seen(seen: dict) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False))


def append_sighting(record: dict) -> None:
    SIGHTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SIGHTINGS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat_id):
        print("WARN: no Telegram creds in env", file=sys.stderr)
        return False
    try:
        subprocess.run(
            ["curl", "-sf", "-X", "POST",
             f"https://api.telegram.org/bot{token}/sendMessage",
             "-d", f"chat_id={chat_id}",
             "-d", f"text={text}",
             "-d", "parse_mode=Markdown"],
            check=True, timeout=10,
        )
        return True
    except Exception as exc:
        print(f"WARN: telegram failed: {exc}", file=sys.stderr)
        return False


def tail_log(n: int = 20000) -> list[str]:
    if not Path(NGINX_LOG).exists():
        return []
    proc = subprocess.run(["tail", "-n", str(n), NGINX_LOG], capture_output=True, text=True)
    return proc.stdout.splitlines()


def classify(ua: str) -> str:
    if not ua or ua == "-":
        return "empty"
    if AGENT_PATTERNS.search(ua):
        return "agent"
    if SKIP_PATTERNS.search(ua):
        return "skip"
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="seed seen state, no alerts")
    ap.add_argument("--dry-run", action="store_true", help="don't write state or notify")
    args = ap.parse_args()

    seen = load_seen()
    new_records: list[dict] = []

    for line in tail_log():
        m = LINE_RE.match(line)
        if not m:
            continue
        g = m.groupdict()
        if g["method"] != "POST" or "/mcp/" not in g["path"]:
            continue
        if not g["status"].startswith(("2", "3")):
            continue
        kind = classify(g["ua"])
        if kind == "skip":
            continue
        key = f"{g['ip']}|{g['ua'] or 'empty'}"
        if key in seen:
            continue
        record = {
            "first_seen": g["ts"],
            "ip": g["ip"],
            "ua": g["ua"],
            "path": g["path"],
            "kind": kind,
        }
        seen[key] = record
        new_records.append(record)

    if args.dry_run:
        for r in new_records:
            print("WOULD ALERT:", json.dumps(r, ensure_ascii=False))
        return 0

    if not args.seed:
        for r in new_records:
            append_sighting(r)
            msg = (
                f"\U0001F6A8 *New MCP client detected*\n"
                f"Kind: `{r['kind']}`\n"
                f"IP: `{r['ip']}`\n"
                f"UA: `{(r['ua'] or 'empty')[:200]}`\n"
                f"Path: `{r['path']}`\n"
                f"Time: {r['first_seen']}"
            )
            send_telegram(msg)

    save_seen(seen)
    print(f"scanned. new={len(new_records)} total_tracked={len(seen)} mode={'seed' if args.seed else 'live'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
