#!/usr/bin/env python3
"""Regenerate app/static/sitemap.xml from DB. Run inside mcp-server: docker exec mcp-server python /app/app/scripts/generate_sitemap.py"""
import os, datetime, psycopg2

BASE = "https://mcp-market.ru"
STATIC_PAGES = ["/", "/pricing", "/demo", "/dashboard", "/quickstart", "/about", "/contacts", "/legal/offer", "/legal/privacy"]
OUT = "/app/app/static/sitemap.xml"

def db_url():
    url = os.environ.get("DATABASE_URL_SYNC")
    if url:
        return url
    from app.config import settings
    return settings.DATABASE_URL_SYNC

conn = psycopg2.connect(db_url())
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='companies'")
cols = {r[0] for r in cur.fetchall()}
ts_col = next((c for c in ("updated_at", "parsed_at", "created_at") if c in cols), None)
cur.execute("SELECT id%s FROM companies" % (", " + ts_col if ts_col else ""))
rows = cur.fetchall()
cur.close(); conn.close()
today = datetime.date.today().isoformat()

def entry(loc, lastmod, freq, prio):
    return "  <url><loc>%s</loc><lastmod>%s</lastmod><changefreq>%s</changefreq><priority>%s</priority></url>" % (loc, lastmod, freq, prio)

parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for p in STATIC_PAGES:
    parts.append(entry(BASE + p, today, "weekly", "1.0" if p == "/" else "0.8"))
for r in rows:
    lm = today
    if ts_col and len(r) > 1 and r[1]:
        try:
            lm = r[1].date().isoformat()
        except Exception:
            lm = str(r[1])[:10]
    parts.append(entry("%s/company/%s" % (BASE, r[0]), lm, "monthly", "0.5"))
parts.append("</urlset>")
tmp = OUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write("\n".join(parts) + "\n")
os.replace(tmp, OUT)
print("sitemap: %d static + %d companies, ts_col=%s" % (len(STATIC_PAGES), len(rows), ts_col))
