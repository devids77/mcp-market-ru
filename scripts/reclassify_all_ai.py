#!/usr/bin/env python3
"""Full AI re-classification of ALL companies using GLM-4.6 with rich context.
Input per company: name, cleaned description, category, city, region.
Usage: python3 -u reclassify_all_ai.py [--limit N] [--dry N] [--offset N]
"""
import os, sys, json, time, ssl, argparse, urllib.request, urllib.error
import psycopg2
from psycopg2.extras import RealDictCursor

DB="postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@127.0.0.1:5432/mcpmarket"
KEY=os.environ.get('Z_AI_API_KEY','').strip()
URL="https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
MODEL="glm-4.6"
TAXONOMY=["каркас","брус","кирпич","газобетон","сип","бревно","коттедж","таунхаус","баня","гараж","бытовка","заборы","кровля","фасад","отделка","ремонт","окна_двери","полы","инженерка","ландшафт","бассейн","снос","монтаж","проектирование","недвижимость","строительство","дом_под_ключ","малоэтажн","многоэтажн"]
SYSTEM="""Ты классификатор российских строительных и смежных компаний. Из входных данных (name+description+category+city+region) верни JSON-массив тегов из таксономии. Никакого дополнительного текста. Правила:
• Анализируй ВСЕ сигналы: ключевые слова в названии (Сканди/Talo/Fin→каркас; Сруб/Изба→бревно; Коттедж/Дача→коттедж), описание, категорию.
• Если description пустой но в name есть явный сигнал ("Каркасные дома Питера") — смело ставь соответствующие теги.
• Общие "Строительная компания" без специфики в name и пустой desc → только ["строительство"].
• Агентство недвижимости/риэлторы/ипотека → ["недвижимость"].
• Не галлюцинируй: лучше пустой массив [], чем неверные теги.
• Ответ — только JSON-массив вида ["тег1","тег2"]
TAXONOMY: """+", ".join(TAXONOMY)
def call(prompt):
    body=json.dumps({"model":MODEL,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}],"thinking":{"type":"disabled"},"max_tokens":200,"temperature":0.1}).encode()
    req=urllib.request.Request(URL,data=body,headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
    ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        d=json.loads(r.read())
        return d['choices'][0]['message']['content']
def parse_tags(text):
    text=text.strip()
    if text.startswith('```'):
        text='\n'.join(text.split('\n')[1:-1])
    text=text.strip()
    try:
        arr=json.loads(text)
        if isinstance(arr,list):
            return [t for t in arr if isinstance(t,str) and t in TAXONOMY]
    except:pass
    return []
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--limit',type=int,default=0)
    ap.add_argument('--dry',type=int,default=0)
    ap.add_argument('--offset',type=int,default=0)
    args=ap.parse_args()
    if not KEY:
        print('ERROR: Z_AI_API_KEY not set');sys.exit(1)
    conn=psycopg2.connect(DB);cur=conn.cursor(cursor_factory=RealDictCursor)
    n=args.dry if args.dry else (args.limit if args.limit else 999999)
    cur.execute("SELECT id,name,description,category,city,region FROM companies ORDER BY id OFFSET %s LIMIT %s",(args.offset,n))
    rows=cur.fetchall()
    print(f'Loaded {len(rows)} companies, dry={bool(args.dry)}',flush=True)
    ok=fail=skip=0;t0=time.time()
    for i,r in enumerate(rows):
        try:
            desc=(r['description'] or '').strip()[:600]
            prompt=f"name: {r['name']}\ndescription: {desc or '<empty>'}\ncategory: {r['category'] or ''}\ncity: {r['city'] or ''}\nregion: {r['region'] or ''}"
            txt=call(prompt)
            tags=parse_tags(txt)
            if not args.dry:
                cur.execute("UPDATE companies SET tags=%s WHERE id=%s",(tags,r['id']))
                if i%20==19:conn.commit()
            ok+=1
            print(f'[{i+1}/{len(rows)}] {r["name"][:40]} -> {tags}',flush=True)
        except urllib.error.HTTPError as e:
            fail+=1;print(f'[{i+1}/{len(rows)}] HTTP {e.code}: {r["name"][:40]}',flush=True)
            if e.code==429:time.sleep(8)
        except Exception as e:
            fail+=1;print(f'[{i+1}/{len(rows)}] ERR: {r["name"][:40]} | {e}',flush=True)
        time.sleep(0.15)
    if not args.dry:conn.commit()
    print(f'\n=== DONE: ok={ok} fail={fail} skip={skip} elapsed={time.time()-t0:.1f}s ===',flush=True)
    cur.close();conn.close()
if __name__=='__main__':main()
