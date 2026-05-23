import json,time,uuid,re,sys,psycopg2,requests
sys.path.insert(0, "/opt/mcp-market/scripts")
from tag_classifier import classify
from datetime import datetime
DB="postgresql://mcpuser:McpMarket2026Secure@127.0.0.1:5432/mcpmarket"
KEY="30cec148-c9c8-4325-a82d-9d922a3b7b3e"
CITIES={"Москва":{"loc":"37.6173,55.7558","r":"Московская область"},"Санкт-Петербург":{"loc":"30.3141,59.9386","r":"Ленинградская область"},"Краснодар":{"loc":"38.9760,45.0353","r":"Краснодарский край"},"Новосибирск":{"loc":"82.9204,55.0302","r":"Новосибирская область"},"Екатеринбург":{"loc":"60.6122,56.8519","r":"Свердловская область"},"Казань":{"loc":"49.1082,55.7964","r":"Республика Татарстан"},"Тюмень":{"loc":"65.5619,57.1522","r":"Тюменская область"},"Воронеж":{"loc":"39.2003,51.6615","r":"Воронежская область"},"Ростов-на-Дону":{"loc":"39.7015,47.2357","r":"Ростовская область"},"Самара":{"loc":"50.1500,53.1959","r":"Самарская область"},"Челябинск":{"loc":"61.4029,55.1599","r":"Челябинская область"},"Уфа":{"loc":"55.9579,54.7348","r":"Республика Башкортостан"},"Красноярск":{"loc":"92.8672,56.0097","r":"Красноярский край"},"Пермь":{"loc":"56.2290,58.0105","r":"Пермский край"},"Нижний Новгород":{"loc":"43.9361,56.2965","r":"Нижегородская область"},"Волгоград":{"loc":"44.5018,48.7080","r":"Волгоградская область"},"Омск":{"loc":"73.3686,54.9914","r":"Омская область"},"Иркутск":{"loc":"104.2964,52.2978","r":"Иркутская область"},"Калининград":{"loc":"20.5106,54.7104","r":"Калининградская область"},"Сочи":{"loc":"39.7303,43.5855","r":"Краснодарский край"},"Барнаул":{"loc":"83.7619,53.3463","r":"Алтайский край"},"Хабаровск":{"loc":"135.0719,48.4827","r":"Хабаровский край"},"Владивосток":{"loc":"131.8855,43.1198","r":"Приморский край"},"Тула":{"loc":"37.6173,54.1833","r":"Тульская область"},"Ярославль":{"loc":"39.8917,57.6261","r":"Ярославская область"},"Калуга":{"loc":"36.2754,54.5293","r":"Калужская область"},"Ставрополь":{"loc":"41.9734,45.0428","r":"Ставропольский край"},"Кемерово":{"loc":"86.0853,55.3331","r":"Кемеровская область"},"Тверь":{"loc":"35.9024,56.8587","r":"Тверская область"},"Саратов":{"loc":"46.0086,51.5924","r":"Саратовская область"}}
QS=["строительство домов под ключ","каркасные дома","дома из бруса","строительство из газобетона","строительство коттеджей","модульные дома","строительство из кирпича","СИП дома","агентство недвижимости","продажа загородных домов","строительная компания","проекты домов","ремонт квартир","дизайн интерьера","архитектурное бюро","ландшафтный дизайн","натяжные потолки","строительные материалы"]
def get_db():
    c=psycopg2.connect(DB);c.autocommit=True;return c
def mslug(n):
    t={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',' ':'-'}
    s=''.join(t.get(c,c) for c in n.lower().strip())
    return re.sub(r'-+','-',re.sub(r'[^a-z0-9-]+','',s)).strip('-')[:80]
def ins_co(conn,d):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM companies WHERE LOWER(name)=LOWER(%s) AND LOWER(COALESCE(city,''))=LOWER(COALESCE(%s,''))",(d["name"],d.get("city")))
        ex=cur.fetchone()
        if ex:
            cur.execute("UPDATE companies SET phone=COALESCE(NULLIF(%s,''),phone),website=COALESCE(NULLIF(%s,''),website),rating=COALESCE(%s,rating),reviews_count=GREATEST(COALESCE(%s,0),reviews_count),updated_at=NOW() WHERE id=%s",
                (d.get("phone"),d.get("website"),d.get("rating"),d.get("reviews_count",0),ex[0]))
            return None
        slug=mslug(d["name"])
        for i in range(1,100):
            cur.execute("SELECT 1 FROM companies WHERE slug=%s",(slug,))
            if not cur.fetchone(): break
            slug=mslug(d["name"])+f"-{i}"
        cid=str(uuid.uuid4())
        cur.execute("INSERT INTO companies(id,name,slug,category,subcategories,region,city,address,description,website,phone,rating,reviews_count,source,source_url,source_id,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'auto') ON CONFLICT(slug) DO NOTHING RETURNING id",
            (cid,d["name"],slug,d.get("category","строительство"),d.get("subcategories",[]),d.get("region"),d.get("city"),d.get("address"),d.get("description"),d.get("website"),d.get("phone"),d.get("rating"),d.get("reviews_count",0),"2gis",d.get("source_url"),d.get("source_id")))
        r=cur.fetchone()
        new_id = r[0] if r else None
        if new_id:
            try:
                tags = classify(d.get("name","") or "", d.get("description","") or "")
                if tags:
                    cur.execute("UPDATE companies SET tags=%s WHERE id=%s",(tags,new_id))
            except Exception as e:
                print(f"  classify err: {e}", file=sys.stderr)
        return new_id
def ins_pr(conn,p,cid):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE name=%s AND company_id=%s",(p["name"],cid))
        if cur.fetchone(): return None
        pid=str(uuid.uuid4())
        cur.execute("INSERT INTO projects(id,company_id,name,area,floors,material,price,bedrooms,bathrooms,description) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
            (pid,cid,p["name"],p.get("area",0),p.get("floors",1),p.get("material",""),p.get("price",0),p.get("bedrooms",0),p.get("bathrooms",0),p.get("description","")))
        r=cur.fetchone()
        return r[0] if r else None
def s2g(q,loc,pg=1):
    try:
        r=requests.get("https://catalog.api.2gis.com/3.0/items",params={"q":q,"location":loc,"key":KEY,"page":pg,"page_size":10,"fields":"items.contact_groups,items.reviews,items.description,items.rubrics","type":"branch","locale":"ru_RU"},timeout=15)
        return r.json() if r.status_code==200 else None
    except: return None
def p2g(item,city,reg):
    ph=ws=None
    for g in item.get("contact_groups",[]):
        for c in g.get("contacts",[]):
            if c.get("type")=="phone" and not ph: ph=c.get("text")
            if c.get("type")=="website" and not ws: ws=c.get("url") or c.get("text")
    rv=item.get("reviews",{});cat="строительство";subs=[]
    for rb in item.get("rubrics",[]):
        rn=rb.get("name","").lower()
        if "каркас" in rn: cat="каркасные_дома";subs.append("каркасные")
        elif "брус" in rn or "деревян" in rn: cat="дома_из_бруса";subs.append("брус")
        elif "газобетон" in rn or "блоч" in rn: cat="газобетон";subs.append("газобетон")
        elif "кирпич" in rn: cat="кирпич";subs.append("кирпич")
        elif "модул" in rn: cat="модульные_дома";subs.append("модульные")
        elif "сип" in rn.lower(): cat="СИП";subs.append("СИП")
        elif "недвижим" in rn: cat="недвижимость";subs.append("недвижимость")
        elif "строит" in rn: subs.append("строительство")
    return {"name":item.get("name_ex",{}).get("primary",item.get("name","")),"category":cat,"subcategories":list(set(subs)) or ["строительство"],"region":reg,"city":city,"address":item.get("address_name",""),"description":item.get("description",""),"website":ws,"phone":ph,"rating":rv.get("rating"),"reviews_count":rv.get("count",0),"source_url":f"https://2gis.ru/search/{item.get('id','')}","source_id":str(item.get("id",""))}
def parse_cos(conn):
    print(f"\n{'='*60}\nПАРСИНГ КОМПАНИЙ: {len(CITIES)} городов x {len(QS)} запросов\n{'='*60}")
    added=0
    for city,info in CITIES.items():
        for q in QS:
            sys.stdout.write(f"\r[{city}] {q[:35]}...");sys.stdout.flush()
            for pg in range(1,6):
                data=s2g(q,info["loc"],pg)
                if not data or "result" not in data: break
                items=data["result"].get("items",[])
                if not items: break
                for item in items:
                    try:
                        r=ins_co(conn,p2g(item,city,info["r"]))
                        if r: added+=1
                    except: pass
                if pg*10>=data["result"].get("total",0): break
                time.sleep(0.3)
            time.sleep(0.2)
    print(f"\nНовых компаний: {added}")
    return added
def gen_projects(conn):
    print(f"\n{'='*60}\nГЕНЕРАЦИЯ ПРОЕКТОВ\n{'='*60}")
    tpl={"каркасные_дома":([60,75,85,100,110,120,135,150,170,200],"каркас",28000),"дома_из_бруса":([70,85,100,120,140,160,180],"брус",35000),"газобетон":([80,100,120,140,160,180,200],"газобетон",33000),"кирпич":([90,110,130,160,200],"кирпич",42000),"модульные_дома":([25,35,45,60,80],"модульный",30000),"СИП":([60,80,100,120,140],"СИП",30000),"строительство":([80,100,120,150,180],"каркас",32000)}
    rmul={"Москва":1.3,"Санкт-Петербург":1.3,"Сочи":1.15,"Калининград":1.15,"Омск":0.85,"Волгоград":0.85,"Иркутск":0.85}
    added=0
    with conn.cursor() as cur:
        cur.execute("SELECT c.id,c.name,c.category,c.city FROM companies c LEFT JOIN projects p ON p.company_id=c.id WHERE p.id IS NULL AND c.category!='недвижимость' AND c.rating IS NOT NULL AND c.rating>=3.5 ORDER BY c.rating DESC LIMIT 300")
        cos=cur.fetchall()
    for cid,cname,cat,city in cos:
        areas,mat,ppsm=tpl.get(cat,tpl["строительство"])
        mul=rmul.get(city,1.0)
        for area in areas:
            fl=1 if area<=100 else 2;bd=max(1,area//40);bt=max(1,bd//2)
            price=int(area*ppsm*mul)
            name=f"{cname} — {mat.title()} {area}"[:200]
            desc=f"Проект дома {area} кв.м от {cname}, {city}. {fl} эт., {bd} спален. {mat.title()}. Цена: {price:,} руб."
            r=ins_pr(conn,{"name":name,"area":area,"floors":fl,"material":mat,"price":price,"bedrooms":bd,"bathrooms":bt,"description":desc},cid)
            if r: added+=1
        if added%200==0 and added>0: sys.stdout.write(f"\r  Проектов: {added}...");sys.stdout.flush()
    print(f"\nНовых проектов: {added}")
    return added
def main():
    start=datetime.now()
    print(f"\n{'#'*60}\n# MCP Market — Полный парсинг\n# {start:%Y-%m-%d %H:%M:%S}\n{'#'*60}")
    conn=get_db()
    nc=parse_cos(conn)
    np=gen_projects(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM companies");tc=cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM projects");tp=cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT city) FROM companies");tci=cur.fetchone()[0]
    conn.close()
    el=(datetime.now()-start).total_seconds()
    print(f"\n{'#'*60}\n# ИТОГО: {tc} компаний, {tp} проектов, {tci} городов\n# Новых: +{nc} компаний, +{np} проектов\n# Время: {el:.0f} сек\n{'#'*60}\n")
if __name__=="__main__": main()
