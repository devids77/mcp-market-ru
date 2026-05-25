#!/usr/bin/env python3
"""
Setup script for Tasks API on MCP Market VPS.
Run this on the VPS to:
1. Create tables in PostgreSQL
2. Seed initial data
3. Inject API endpoints into main.py
"""

import subprocess
import os

MAIN_PY = '/opt/mcp-market/app/main.py'
SQL_FILE = '/opt/mcp-market/migrate_and_seed.sql'

def run_sql():
    """Run migration SQL via docker exec."""
    print("=== Running SQL migration ===")
    with open(SQL_FILE, 'r') as f:
        sql = f.read()
    result = subprocess.run(
        ['docker', 'exec', '-i', 'mcp-db', 'psql', '-U', 'mcpuser', '-d', 'mcpmarket'],
        input=sql, capture_output=True, text=True
    )
    print("STDOUT:", result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
    return result.returncode == 0


def inject_api_endpoints():
    print("\n=== Injecting API endpoints into main.py ===")
    with open(MAIN_PY, 'r') as f:
        content = f.read()
    if '/api/tasks' in content:
        print("API endpoints already present, skipping.")
        return True
    marker = '@app.get("/tasks"'
    if marker not in content:
        print(f"ERROR: Marker not found")
        return False
    api_code = open('/opt/mcp-market/tasks_api_code.py').read()
    content = content.replace(marker, api_code + '\n' + marker)
    with open(MAIN_PY, 'w') as f:
        f.write(content)
    print("API endpoints injected successfully.")
    return True


if __name__ == '__main__':
    ok1 = run_sql()
    ok2 = inject_api_endpoints()
    if ok1 and ok2:
        print("\n=== SUCCESS ===")
    else:
        print("\n=== SOME STEPS FAILED ===")
