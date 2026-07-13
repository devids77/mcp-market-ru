import os
import json,time,uuid,re,psycopg2,psycopg2.extras,requests

DB_URL="postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@127.0.0.1:5432/mcpmarket"
API_KEY=os.environ.get("DGIS_API_KEY", "")

QUERIES=["строительство домов под ключ","каркасные дома","дома из бруса","строительство домов из газобетона","строительство коттеджей","модульные дома","агентство недвижимости"]
CITIES={
    "Москва":{"loc":"37.6173,55.7558","region":"Московская область"},
    "Санкт-Петербург":{"loc":"30.3141,59.9386","region":"Ленинградская область"},
    "Краснодар":{"loc":"38.9760,45.0353","region":"Краснодарский край"},
    "Новосибирск":{"loc":"82.9204,55.0302","region":"Новосибирская область"},
    "Екатеринбург":{"loc":"60.6122,56.8519","region":"Свердловская область"},
    "Казань":{"loc":"49.1082,55.7964","region":"Республика Татарстан"},
    "Тюмень":{"loc":"65.5619,57.1522","region":"Тюменская область"},
}

def get_db():
    conn=psycopg2.connect(DB_URL);conn.autocommit=True;return conn

def make_slug(name):
    t={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',' ':'-'}
    s=''.join(t.get(c,c) for c in name.lower().strip())
    return re.sub(r'-+','-',re.sub(r'[^a-z0-9-]+','',s)).strip('-')[:80]

def insert_company(conn,d):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM companies WHERE LOWER(name)=LOWER(%s) AND LOWER(COALESCE(city,''))=LOWER(COALESCE(%s,''))",(d["name"],d.get("city")))
        if cur.fetchone(): return None
        slug=make_slug(d["name"])
        for i in range(1,100):
            cur.execute("SELECT 1 FROM companies WHERE slug=%s",(slug,))
            if not cur.fetchone(): break
            slug=make_slug(d["name"])+f"-{i}"
        cid=str(uuid.uuid4())
        cur.execute("""INSERT INTO companies(id,name,slug,category,subcategories,region,city,address,description,website,phone,rating,reviews_count,source,source_url,source_id,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'auto') ON CONFLICT(slug) DO NOTHING RETURNING id""",
            (cid,d["name"],slug,d.get("category","строительство"),d.get("subcategories",[]),d.get("region"),d.get("city"),d.get("address"),d.get("description"),d.get("website"),d.get("phone"),d.get("rating"),d.get("reviews_count",0),"2gis",d.get("source_url"),d.get("source_id")))
        r=cur.fetchone()
        return r[0] if r else None

def search_2gis(query,location,page=1):
    try:
        r=requests.get("https://catalog.api.2gis.com/3.0/items",params={
            "q":query,
            "location":location,
            "key":API_KEY,
            "page":page,
            "page_size":10,
            "fields":"items.contact_groups,items.reviews,items.description,items.rubrics",
            "type":"branch",
            "locale":"ru_RU"
        },timeout=15)
        if r.status_code==200:
            return r.json()
        else:
            print(f"  API {r.status_code}")
            return None
    except Exception as e:
        print(f"  ERR: {e}");return None

def parse_item(item,city,region):
    phone=website=None
    for g in item.get("contact_groups",[]):
        for c in g.get("contacts",[]):
            if c.get("type")=="phone" and not phone: phone=c.get("text")
            if c.get("type")=="website" and not website: website=c.get("url") or c.get("text")
    rv=item.get("reviews",{})
    cat="строительство"
    subs=[]
    for rb in item.get("rubrics",[]):
        rn=rb.get("name","").lower()
        if "каркас" in rn: cat="каркасные_дома";subs.append("каркасные")
        elif "брус" in rn or "деревян" in rn: cat="дома_из_бруса";subs.append("брус")
        elif "газобетон" in rn: cat="газобетон";subs.append("газобетон")
        elif "недвижим" in rn: cat="недвижимость";subs.append("недвижимость")
        elif "строит" in rn: subs.append("строительство")
    return {"name":item.get("name_ex",{}).get("primary",item.get("name","")),"category":cat,"subcategories":list(set(subs)) or ["строительство"],"region":region,"city":city,"address":item.get("address_name",""),"description":item.get("description",""),"website":website,"phone":phone,"rating":rv.get("rating"),"reviews_count":rv.get("count",0),"source_url":f"https://2gis.ru/search/{item.get('id','')}","source_id":str(item.get("id",""))}

def main():
    print("="*50);print("MCP Market — Парсер 2ГИС");print("="*50)
    conn=get_db();added=skipped=errors=0
    for city,info in CITIES.items():
        for q in QUERIES:
            print(f"[{city}] {q}",end="",flush=True)
            for page in range(1,6):
                data=search_2gis(q,info["loc"],page)
                if not data or "result" not in data: break
                items=data["result"].get("items",[])
                if not items: break
                for item in items:
                    try:
                        r=insert_company(conn,parse_item(item,city,info["region"]))
                        if r: added+=1
                        else: skipped+=1
                    except Exception as e: errors+=1
                total=data["result"].get("total",0)
                if page*10>=total: break
                time.sleep(0.3)
            print(f" → +{added} всего")
            time.sleep(0.2)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM companies");total=cur.fetchone()[0]
    conn.close()
    print(f"\n{'='*50}\nДобавлено: {added}\nДубли: {skipped}\nОшибок: {errors}\nВсего в базе: {total}\n{'='*50}")

if __name__=="__main__": main()
