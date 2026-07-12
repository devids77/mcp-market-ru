#!/usr/bin/env python3
"""Enrich phone/email from 2GIS for companies missing contacts."""
import re, sys, time, logging, random, json, psycopg2
from urllib.request import Request, urlopen
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@localhost:5432/mcpmarket'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'

# 2GIS catalog API (public, no key needed)
API_BASE = 'https://catalog.api.2gis.com/3.0/items'
API_KEY = 'rujany7162'  # Public 2GIS web key

def search_2gis(company_name, city):
    """Search 2GIS API for company contacts."""
    query = f"{company_name} {city}"
    url = f"{API_BASE}?q={quote(query)}&key={API_KEY}&fields=items.contact_groups,items.org&page_size=3"
    try:
        req = Request(url, headers={'User-Agent': UA, 'Referer': 'https://2gis.ru/'})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            items = data.get('result', {}).get('items', [])
            if items:
                return items[0]
    except Exception as e:
        log.debug(f"2GIS API error: {e}")
    return None

def extract_contacts(item):
    """Extract phone and email from 2GIS item."""
    phone = None
    email = None
    website = None
    
    contact_groups = item.get('contact_groups', [])
    for group in contact_groups:
        for contact in group.get('contacts', []):
            ctype = contact.get('type', '')
            cvalue = contact.get('value', '')
            if ctype == 'phone' and not phone:
                phone = contact.get('text', cvalue)
            elif ctype == 'email' and not email:
                email = cvalue
            elif ctype == 'website' and not website:
                website = cvalue
    
    return phone, email, website

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else None
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # Get companies missing phone AND email
    if region:
        cur.execute("""SELECT id, name, city, website FROM companies 
                       WHERE region=%s AND phone IS NULL
                       ORDER BY id""", (region,))
    else:
        cur.execute("""SELECT id, name, city, website FROM companies 
                       WHERE phone IS NULL
                       ORDER BY id""")
    
    companies = cur.fetchall()
    log.info(f"Found {len(companies)} companies without phone" + (f" in {region}" if region else ""))
    
    updated = 0
    for i, (cid, name, city, website) in enumerate(companies):
        try:
            item = search_2gis(name, city or '')
            if not item:
                log.info(f"  [{i+1}/{len(companies)}] {name}: not found on 2GIS")
                time.sleep(random.uniform(1, 2))
                continue
            
            phone, email, site = extract_contacts(item)
            
            updates = []
            params = []
            if phone:
                updates.append("phone = %s")
                params.append(phone)
            if email:
                updates.append("email = COALESCE(email, %s)")
                params.append(email)
            if site and not website:
                updates.append("website = %s")
                params.append(site)
            
            if updates:
                params.append(cid)
                sql = f"UPDATE companies SET {', '.join(updates)} WHERE id = %s"
                cur.execute(sql, params)
                conn.commit()
                updated += 1
                log.info(f"  [{i+1}/{len(companies)}] {name}: phone={phone}, email={email}, site={site}")
            else:
                log.info(f"  [{i+1}/{len(companies)}] {name}: found but no contacts")
            
        except Exception as e:
            log.error(f"  [{i+1}/{len(companies)}] Error {name}: {e}")
        
        time.sleep(random.uniform(0.5, 1.5))
    
    log.info(f"=== DONE: {updated} companies updated out of {len(companies)} ===")
    conn.close()

if __name__ == '__main__':
    main()
