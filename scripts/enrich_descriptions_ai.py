"""AI-driven description enricher (GLM-4.6 via Z.AI Coding Pro). 2026-04-25.
Fetches website HTML, sends to GLM-4.6 with prompt "extract what company does in 200-400 chars",
updates companies.description. Usage: python3 -u enrich_descriptions_ai.py [--limit N] [--dry N]
"""
import os, sys, re, ssl, json, time, argparse
import urllib.request, urllib.error
import psycopg2
from psycopg2.extras import RealDictCursor

DB = "postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@localhost:5432/mcpmarket"
ENDPOINT = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
MODEL = "glm-4.6"
SYSTEM = ("Ты извлекаешь краткое описание российской строительной компании из HTML её сайта. "
          "Верни 1-3 предложения (200-400 символов), описывающие ЧЕМ КОНКРЕТНО занимается компания: "
          "услуги, специализация, регион. Без маркетинга, fluff и приглашений. "
          "Если HTML непонятный или не по теме — верни пустую строку.")

def fetch_html(url, timeout=15):
    if not url.startswith("http"):
        url = "https://" + url
    try:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read(300000)
        ct = r.headers.get("Content-Type", "")
        enc = "utf-8"
        if "charset=" in ct:
            enc = ct.split("charset=")[1].split(";")[0].strip()
        return raw.decode(enc, errors="replace")
    except Exception as e:
        return None

def html_to_text(html, limit=4000):
    if not html: return ""
    h = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S|re.I)
    h = re.sub(r"<style[^>]*>.*?</style>", "", h, flags=re.S|re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h[:limit]

def call_llm(api_key, name, text):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role":"system","content":SYSTEM}, {"role":"user","content":f"Компания: {name}\n\nHTML-текст сайта:\n{text}"}],
        "max_tokens": 350,
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"].get("content", "").strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", type=int, default=0)
    args = ap.parse_args()
    api_key = os.environ.get("Z_AI_API_KEY", "").strip()
    if not api_key:
        print("Z_AI_API_KEY not set"); sys.exit(1)
    conn = psycopg2.connect(DB); cur = conn.cursor(cursor_factory=RealDictCursor)
    sql = """SELECT id, name, website FROM companies
             WHERE website IS NOT NULL AND website != ''
               AND (description IS NULL OR description = '' OR LENGTH(description) < 40)
             ORDER BY reviews_count DESC NULLS LAST"""
    if args.limit: sql += f" LIMIT {args.limit}"
    elif args.dry: sql += f" LIMIT {args.dry}"
    cur.execute(sql); rows = cur.fetchall()
    print(f"Found {len(rows)} companies to enrich")
    ok, fail, skip = 0, 0, 0; t0 = time.time()
    for i, r in enumerate(rows):
        try:
            html = fetch_html(r["website"], timeout=12)
            if not html:
                skip += 1; print(f"[{i+1}/{len(rows)}] FETCH_FAIL: {r['name'][:40]} | {r['website'][:50]}"); continue
            text = html_to_text(html, 4000)
            if len(text) < 100:
                skip += 1; print(f"[{i+1}/{len(rows)}] HTML_TOO_SHORT: {r['name'][:40]}"); continue
            desc = call_llm(api_key, r["name"], text)
            if not desc or len(desc) < 30:
                skip += 1; print(f"[{i+1}/{len(rows)}] LLM_EMPTY: {r['name'][:40]}"); continue
            if not args.dry:
                cur.execute("UPDATE companies SET description = %s WHERE id = %s", (desc[:1000], r["id"]))
                if i % 10 == 9: conn.commit()
            ok += 1
            print(f"[{i+1}/{len(rows)}] OK: {r['name'][:40]} -> {desc[:80]}...")
        except urllib.error.HTTPError as e:
            fail += 1; print(f"[{i+1}/{len(rows)}] HTTP {e.code}: {r['name'][:40]}")
            if e.code == 429: time.sleep(5)
        except Exception as e:
            fail += 1; print(f"[{i+1}/{len(rows)}] ERR: {r['name'][:40]} | {e}")
        time.sleep(0.2)
    if not args.dry: conn.commit()
    print(f"\n=== DONE: ok={ok}, fail={fail}, skip={skip}, elapsed={time.time()-t0:.1f}s ===")
    cur.close(); conn.close()

if __name__ == "__main__":
    main()
