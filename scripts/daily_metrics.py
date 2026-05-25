#!/usr/bin/env python3
"""Daily metrics snapshot.

Run via cron 09:00 local. Aggregates:
- DB counts (companies, projects, tags coverage, leads, api_keys)
- Agent traffic from data/agent_seen.json + jsonl
- Recent registration activity

Writes to data/daily_metrics.jsonl (append-only) and sends a digest to Telegram.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path("/opt/mcp-market")
METRICS_FILE = ROOT / "data" / "daily_metrics.jsonl"
SEEN_FILE = ROOT / "data" / "agent_seen.json"
SIGHTINGS_FILE = ROOT / "data" / "agent_sightings.jsonl"


def db_stats() -> dict:
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
    )
    out = {}
    with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM companies"); out["companies"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM projects"); out["projects"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM companies WHERE array_length(tags, 1) > 0"); out["with_tags"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM companies WHERE website IS NOT NULL AND website <> ''"); out["with_website"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM leads"); out["leads"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM api_keys"); out["api_keys"] = cur.fetchone()["n"]
        try:
            cur.execute("SELECT COUNT(*) AS n FROM usage_logs WHERE created_at > now() - interval '24 hours'")
            out["requests_24h"] = cur.fetchone()["n"]
        except Exception:
            out["requests_24h"] = None
        try:
            cur.execute("SELECT COUNT(*) AS n FROM api_keys WHERE last_used_at > now() - interval '24 hours'")
            out["api_keys_active_24h"] = cur.fetchone()["n"]
        except Exception:
            out["api_keys_active_24h"] = None
    return out


def agent_stats() -> dict:
    seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
    from collections import Counter
    ua_counts = Counter(v["ua"] or "(empty)" for v in seen.values())
    new_in_jsonl = 0
    if SIGHTINGS_FILE.exists():
        for _ in SIGHTINGS_FILE.open(): new_in_jsonl += 1
    return {
        "unique_external_clients": len(seen),
        "top_uas": dict(ua_counts.most_common(5)),
        "alerts_logged_total": new_in_jsonl,
    }


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat_id): return False
    try:
        subprocess.run(
            ["curl", "-sf", "-X", "POST",
             f"https://api.telegram.org/bot{token}/sendMessage",
             "-d", f"chat_id={chat_id}",
             "--data-urlencode", f"text={text}",
             "-d", "parse_mode=Markdown"],
            check=True, timeout=10,
        )
        return True
    except Exception as exc:
        print("telegram error:", exc, file=sys.stderr)
        return False


def main() -> int:
    now = datetime.now(timezone.utc)
    db = db_stats()
    ag = agent_stats()
    record = {"date": now.strftime("%Y-%m-%d"), "ts": now.isoformat(), "db": db, "agents": ag}
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    digest = (
        f"\U0001F4CA *Daily MCP Market digest — {record['date']}*\n\n"
        f"Companies: `{db['companies']}` (with tags: `{db['with_tags']}`, website: `{db['with_website']}`)\n"
        f"Projects: `{db['projects']}`\n"
        f"Leads: `{db['leads']}` | API keys: `{db['api_keys']}`\n"
        f"Requests 24h: `{db.get('requests_24h', '?')}` | Active keys 24h: `{db.get('api_keys_active_24h', '?')}`\n\n"
        f"Unique external clients tracked: `{ag['unique_external_clients']}`\n"
        f"Top UAs: {', '.join(f'`{k}`x{v}' for k,v in list(ag['top_uas'].items())[:5])}\n"
        f"Alerts in jsonl: `{ag['alerts_logged_total']}`"
    )
    print(digest)
    send_telegram(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
