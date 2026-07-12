import json, uuid, psycopg2, psycopg2.extras

DB = 'postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@127.0.0.1:5432/mcpmarket'
conn = psycopg2.connect(DB)
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

with open('/opt/mcp-market/scripts/scandieco_all.json') as f:
    projects = json.load(f)

cur.execute("SELECT id FROM companies WHERE name = 'СкандиЭкоДом'")
company_id = str(cur.fetchone()['id'])
print(f'Company ID: {company_id}')
print(f'Projects to process: {len(projects)}')

imported = 0
for p in projects:
    title = p.get('title') or p.get('id')
    area = p.get('area_m2')
    if not title or not area: continue
    cur.execute('SELECT 1 FROM projects WHERE name = %s AND company_id = %s', (title, company_id))
    if cur.fetchone(): continue
    floors_raw = p.get('floors', '')
    floors = 2 if '2' in str(floors_raw) else (3 if '3' in str(floors_raw) else 1)
    price = int(p['price_from']) if p.get('price_from') else None
    price_desc = None
    if p.get('price_from') and p.get('price_to'):
        price_desc = f"от {int(p['price_from']):,} до {int(p['price_to']):,} руб.".replace(',', ' ')
    ppsm = int(price / area) if price and area else None
    cur.execute('''INSERT INTO projects (id, company_id, name, area, floors, bedrooms, bathrooms, material, style, price, price_per_sqm, price_description, url, source, description)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
        (str(uuid.uuid4()), company_id, title, area, floors, p.get('bedrooms'), p.get('bathrooms'),
         'каркас', p.get('style'), price, ppsm, price_desc, p.get('site_url'), 'scandiecodom_api',
         f"Каркасный дом {title}, {area} м2, {floors_raw}. СкандиЭкоДом."))
    imported += 1

cur.execute('UPDATE companies SET projects_count = (SELECT COUNT(*) FROM projects WHERE company_id = %s) WHERE id = %s', (company_id, company_id))
cur.execute('SELECT COUNT(*) as cnt FROM projects WHERE company_id = %s', (company_id,))
total = cur.fetchone()['cnt']
print(f'New imported: {imported}')
print(f'Total projects: {total}')
conn.close()
