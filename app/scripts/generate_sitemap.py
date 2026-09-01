#!/usr/bin/env python3
"""Regenerate app/static/sitemap.xml from DB. Run inside mcp-server: docker exec mcp-server python /app/app/scripts/generate_sitemap.py"""
import os, datetime, psycopg2

BASE = "https://mcp-market.ru"
STATIC_PAGES = ["/", "/catalog", "/pricing", "/demo", "/dashboard", "/quickstart", "/about", "/contacts", "/legal/offer", "/legal/privacy"]

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slugify(value):
    """Must match _slugify in app/main.py or the sitemap points at 404s."""
    import re as _re
    t = "".join(_TRANSLIT.get(ch, ch) for ch in (value or "").strip().lower())
    t = _re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "n-a"
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
# Catalog landings: these are the pages regional queries actually land on,
# so they must be in the sitemap or Yandex will never discover them.
cat_col = 0
try:
    # The main cursor is already closed by this point, so take a fresh one.
    _c2 = psycopg2.connect(db_url())
    _cur2 = _c2.cursor()
    _cur2.execute("SELECT DISTINCT category, region FROM companies "
                  "WHERE category IS NOT NULL AND category <> '' "
                  "AND region IS NOT NULL AND region <> ''")
    pairs = _cur2.fetchall()
    _cur2.close(); _c2.close()
    seen_cats = set()
    for cat, reg in pairs:
        cs = _slugify(cat)
        if cs not in seen_cats:
            seen_cats.add(cs)
            parts.append(entry("%s/catalog/%s" % (BASE, cs), today, "weekly", "0.7"))
            cat_col += 1
        parts.append(entry("%s/catalog/%s/%s" % (BASE, cs, _slugify(reg)),
                           today, "weekly", "0.6"))
        cat_col += 1
except Exception as _e:
    print("catalog urls skipped:", _e)

parts.append("</urlset>")
tmp = OUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write("\n".join(parts) + "\n")
os.replace(tmp, OUT)
print("sitemap: %d static + %d companies + %d catalog, ts_col=%s"
      % (len(STATIC_PAGES), len(rows), cat_col, ts_col))
