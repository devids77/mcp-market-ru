"""AI classifier (GLM-4.6 via Z.AI Coding Pro endpoint) — Phase 2, 2026-04-24.
Classifies companies that regex-classifier missed (empty tags), sends prompt to glm-4.6, parses JSON, writes to tags[].
Usage: python3 tag_classifier_ai.py [--dry N] [--commit] [--limit N]
"""
import os, sys, json, time, argparse, re, urllib.request, urllib.error
import psycopg2
from psycopg2.extras import RealDictCursor

ENDPOINT = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
MODEL = "glm-4.6"
TAXONOMY = ["каркас","брус","кирпич","газобетон","сип","бревно","коттедж","таунхаус","баня","гараж","бытовка","заборы","кровля","фасад","отделка","ремонт","окна_двери","полы","инженерка","ландшафт","бассейн","снос","монтаж","проектирование","недвижимость","строительство","дом_под_ключ","малоэтажн","многоэтажн"]

SYSTEM = ("Ты классификатор российских строительных компаний. По названию (и описанию если есть) определи теги из таксономии: "
          + ", ".join(TAXONOMY) + ". Верни ТОЛЬКО JSON-массив выбранных тегов без пояснений и markdown. Если не можешь определить — верни []. "
          "Не выдумывай теги вне таксономии. Максимум 5 тегов на компанию.")

def call_llm(api_key, name, description, website=""):
    user_msg = f"name: {name or ''}\ndescription: {description or ''}\nwebsite: {website or ''}"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role":"system","content":SYSTEM},{"role":"user","content":user_msg}],
        "max_tokens": 200,
        "thinking": {"type": "disabled"},
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    content = d["choices"][0]["message"].get("content","").strip()
    # GLM может вернуть массив в markdown ```json ... ``` — выдернем
    m = re.search(r"\[.*?\]", content, re.DOTALL)
    if not m:
        return []
    try:
        tags = json.loads(m.group(0))
        return [t for t in tags if t in TAXONOMY][:5]
    except Exception:
        return []

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", type=int, default=0, help="Print N samples, don't write")
    ap.add_argument("--commit", action="store_true", help="Write to DB")
    ap.add_argument("--limit", type=int, default=0, help="Process only N rows (0=all)")
    args = ap.parse_args()
    api_key = os.environ.get("Z_AI_API_KEY","").strip()
    if not api_key:
        print("ERROR: Z_AI_API_KEY not set"); sys.exit(1)
    print(f"Endpoint: {ENDPOINT}\nModel: {MODEL}\nKey: {api_key[:20]}...")
    conn = psycopg2.connect(host=os.environ.get("DB_HOST", "mcp-db"), dbname=os.environ.get("DB_NAME", "mcpmarket"), user=os.environ.get("DB_USER", "mcpuser"), password=os.environ["DB_PASSWORD"])
    cur = conn.cursor(cursor_factory=RealDictCursor)
    sql = "SELECT id, name, description, website FROM companies WHERE tags IS NULL OR array_length(tags,1) IS NULL OR array_length(tags,1)=0"
    if args.limit:
        sql += f" LIMIT {args.limit}"
    cur.execute(sql)
    rows = cur.fetchall()
    print(f"Companies without tags: {len(rows)}")
    ok, fail, t0 = 0, 0, time.time()
    for i, r in enumerate(rows):
        try:
            tags = call_llm(api_key, r["name"], r["description"], r.get("website",""))
            ok += 1
            if args.dry and i < args.dry:
                print(f"  [{i+1}/{len(rows)}] {r['name'][:40]!r} -> {tags}")
            if args.commit and tags:
                cur.execute("UPDATE companies SET tags = %s WHERE id = %s", (tags, r["id"]))
                if i % 25 == 24:
                    conn.commit()
            if i % 50 == 49:
                rate = (i+1) / (time.time()-t0)
                print(f"  progress: {i+1}/{len(rows)} ({rate:.1f}/sec, ok={ok} fail={fail})")
        except urllib.error.HTTPError as e:
            fail += 1
            print(f"  HTTPError {e.code} on {r['name'][:30]!r}: {e.read()[:200].decode(errors='replace')}")
            if e.code == 429:
                time.sleep(5)
        except Exception as e:
            fail += 1
            print(f"  ERR on {r['name'][:30]!r}: {e}")
        time.sleep(0.05)  # 6.5 req/sec rate-limit
        if args.dry and i+1 >= args.dry:
            break
    if args.commit:
        conn.commit()
        print(f"COMMITTED. ok={ok}, fail={fail}, elapsed={time.time()-t0:.1f}s")
    conn.close()
