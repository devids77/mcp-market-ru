import json, psycopg2, psycopg2.extras, requests
from bs4 import BeautifulSoup

DB = "postgresql://mcpuser:McpMarket2026Secure@127.0.0.1:5432/mcpmarket"

# Parse real URLs from scandiecodom.ru catalog
print("Fetching catalog from scandiecodom.ru...")
r = requests.get("https://scandiecodom.ru/katalog-proektov/", timeout=30)
soup = BeautifulSoup(r.text, "html.parser")

mapping = {}
for a in soup.find_all("a", href=True):
    href = a["href"]
    if "/houses/kd-" in href:
        import re
        m = re.search(r"/houses/kd-(\d+)", href)
        if m:
            code = f"КД-{m.group(1)}"
            full_url = href if href.startswith("http") else f"https://scandiecodom.ru{href}"
            mapping[code] = full_url

print(f"Found {len(mapping)} real URLs")

# Update database
conn = psycopg2.connect(DB)
conn.autocommit = True
cur = conn.cursor()

updated = 0
for code, real_url in mapping.items():
    cur.execute("UPDATE projects SET url = %s WHERE name LIKE %s AND source = 'scandiecodom_api'", (real_url, f"{code} |%"))
    if cur.rowcount > 0:
        updated += cur.rowcount
    else:
        cur.execute("UPDATE projects SET url = %s WHERE name = %s AND source = 'scandiecodom_api'", (real_url, code))
        updated += cur.rowcount

print(f"Updated {updated} project URLs")

# Check results
cur.execute("SELECT name, url FROM projects WHERE source = 'scandiecodom_api' AND url LIKE '%/houses/%' LIMIT 5")
for row in cur.fetchall():
    print(f"  {row[0]} -> {row[1]}")

cur.execute("SELECT COUNT(*) FROM projects WHERE source = 'scandiecodom_api' AND (url IS NULL OR url NOT LIKE '%/houses/%')")
missing = cur.fetchone()[0]
print(f"Projects still with old/no URL: {missing}")

conn.close()
