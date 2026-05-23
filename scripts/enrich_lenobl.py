#!/usr/bin/env python3
"""
Enrich Leningrad Oblast companies:
1. Parse company websites for house projects (area, floors, material, price)
2. Extract descriptions, phones, emails from websites
3. Update companies and insert new projects into DB
"""
import os, re, sys, time, json, logging, hashlib
from urllib.parse import urljoin, urlparse
import psycopg2
import psycopg2.extras
import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                    handlers=[logging.FileHandler('enrich_lenobl.log'), logging.StreamHandler()])
log = logging.getLogger(__name__)

DB = os.getenv('DATABASE_URL', 'postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket')

def get_db():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    return conn

# --- EXTRACTORS ---

def extract_phones(text):
    patterns = [
        r'[\+]?[78][\s\-\(]?\d{3}[\s\-\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
        r'8[\s\-]?800[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
    ]
    phones = set()
    for p in patterns:
        for m in re.findall(p, text):
            cleaned = re.sub(r'[^\d+]', '', m)
            if len(cleaned) >= 11:
                if cleaned.startswith('8') and len(cleaned) == 11:
                    cleaned = '+7' + cleaned[1:]
                elif cleaned.startswith('7') and len(cleaned) == 11:
                    cleaned = '+' + cleaned
                phones.add(cleaned)
    return list(phones)

def extract_emails(text):
    return list(set(re.findall(r'[\w\.\-]+@[\w\.\-]+\.\w{2,}', text)))

def extract_price(text):
    """Extract price from text, return integer or None."""
    text = text.replace('\xa0', ' ').replace(' ', '')
    patterns = [
        r'(\d[\d\s]{2,10})\s*(?:руб|₽|р\.)',
        r'(?:от|цена|стоимость)[\s:]*(\d[\d\s]{4,10})',
        r'(\d{1,3}(?:\s?\d{3}){1,3})\s*(?:руб|₽)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = int(re.sub(r'\s', '', m.group(1)))
            if 100000 <= val <= 100000000:
                return val
    return None

def extract_area(text):
    """Extract house area in m2."""
    patterns = [
        r'(\d{2,4}(?:[,\.]\d{1,2})?)\s*(?:м²|м2|кв\.?\s*м)',
        r'(?:площадь|S)[\s:]*(\d{2,4}(?:[,\.]\d{1,2})?)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(',', '.'))
            if 20 <= val <= 1000:
                return val
    return None

def extract_floors(text):
    patterns = [
        r'(\d)\s*(?:этаж|эт\.)',
        r'(?:этажность|этажей)[\s:]*(\d)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 4:
                return val
    return None

def detect_material(text):
    text_lower = text.lower()
    materials = {
        'каркас': ['каркас', 'frame', 'сип', 'sip', 'каркасн'],
        'брус': ['брус', 'timber', 'клеен', 'профилир'],
        'газобетон': ['газобетон', 'газоблок', 'пеноблок', 'aerated'],
        'кирпич': ['кирпич', 'brick'],
        'бревно': ['бревн', 'log'],
    }
    for mat, keywords in materials.items():
        for kw in keywords:
            if kw in text_lower:
                return mat
    return None

def fetch_page(url, timeout=15):
    """Fetch page with retries and proper headers."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=False) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        log.debug(f"Failed to fetch {url}: {e}")
    return None

def find_project_pages(base_url, html):
    """Find links to project/catalog pages."""
    soup = BeautifulSoup(html, 'html.parser')
    project_urls = set()
    keywords = ['проект', 'каталог', 'дом', 'portfolio', 'project', 'catalog',
                'наши-дома', 'nashi-doma', 'строительство', 'house', 'готов']
    for a in soup.find_all('a', href=True):
        href = a['href'].lower()
        text = (a.get_text() or '').lower()
        for kw in keywords:
            if kw in href or kw in text:
                full_url = urljoin(base_url, a['href'])
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    project_urls.add(full_url)
                break
    return list(project_urls)[:10]

def parse_projects_from_page(html, base_url, company_name):
    """Try to extract house projects from a page."""
    soup = BeautifulSoup(html, 'html.parser')
    projects = []
    text = soup.get_text(separator=' ', strip=True)
    
    # Strategy 1: Look for structured project cards
    card_selectors = [
        '.project', '.product', '.house', '.item', '.card',
        '[class*=project]', '[class*=house]', '[class*=catalog]',
        'article', '.portfolio-item'
    ]
    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if len(cards) >= 2:
            break
    
    if len(cards) >= 2:
        for card in cards[:30]:
            card_text = card.get_text(separator=' ', strip=True)
            area = extract_area(card_text)
            if not area:
                continue
            name_el = card.find(['h2', 'h3', 'h4', 'a', '.title', '.name'])
            name = name_el.get_text(strip=True) if name_el else f"Проект {area:.0f} м²"
            if len(name) > 200:
                name = name[:200]
            
            price = extract_price(card_text)
            floors = extract_floors(card_text)
            material = detect_material(card_text)
            
            link_el = card.find('a', href=True)
            url = urljoin(base_url, link_el['href']) if link_el else base_url
            
            projects.append({
                'name': name,
                'area': area,
                'floors': floors or 1,
                'material': material or 'каркас',
                'price': price,
                'description': card_text[:500] if len(card_text) > 20 else None,
                'url': url,
                'source': 'website',
                'source_url': base_url,
            })
    
    # Strategy 2: If no cards found, try regex on full text
    if not projects:
        pattern = r'(?:проект|дом)\s+[«""]?([^«""\n]{3,50})[»""]?\s*.*?(\d{2,4}(?:[,\.]\d)?)\s*м'
        for m in re.finditer(pattern, text, re.IGNORECASE):
            name = m.group(1).strip()
            area = float(m.group(2).replace(',', '.'))
            if 20 <= area <= 1000:
                nearby = text[max(0, m.start()-200):m.end()+200]
                projects.append({
                    'name': name,
                    'area': area,
                    'floors': extract_floors(nearby) or 1,
                    'material': detect_material(nearby) or 'каркас',
                    'price': extract_price(nearby),
                    'description': nearby[:500],
                    'url': base_url,
                    'source': 'website',
                    'source_url': base_url,
                })
    
    return projects[:20]

def enrich_company(conn, company):
    """Enrich a single company by parsing its website."""
    cid = company['id']
    name = company['name']
    website = company['website']
    
    if not website:
        return 0
    
    if not website.startswith('http'):
        website = 'https://' + website
    
    log.info(f"Parsing {name}: {website}")
    
    html = fetch_page(website)
    if not html:
        log.warning(f"  Cannot fetch {website}")
        return 0
    
    soup = BeautifulSoup(html, 'html.parser')
    page_text = soup.get_text(separator=' ', strip=True)
    
    updates = {}
    
    # Extract phone if missing
    if not company.get('phone'):
        phones = extract_phones(page_text)
        if phones:
            updates['phone'] = phones[0]
            log.info(f"  Found phone: {phones[0]}")
    
    # Extract email if missing
    if not company.get('email'):
        emails = extract_emails(page_text)
        if emails:
            updates['email'] = emails[0]
            log.info(f"  Found email: {emails[0]}")
    
    # Extract description if missing or short
    if not company.get('description') or len(company.get('description', '')) < 50:
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content'].strip()
            if len(desc) > 30:
                updates['description'] = desc[:1000]
                log.info(f"  Found description ({len(desc)} chars)")
    
    # Extract price range from page
    prices = []
    for m in re.finditer(r'(\d[\d\s]{4,10})\s*(?:руб|₽|р\.)', page_text):
        val = int(re.sub(r'\s', '', m.group(1)))
        if 100000 <= val <= 100000000:
            prices.append(val)
    
    if prices and not company.get('price_per_sqm_min'):
        min_p = min(prices)
        max_p = max(prices)
        if min_p != max_p:
            updates['min_project_price'] = min_p
            updates['max_project_price'] = max_p
            log.info(f"  Found price range: {min_p:,} - {max_p:,}")
    
    # Update company
    if updates:
        sets = ', '.join(f"{k} = %s" for k in updates)
        vals = list(updates.values())
        vals.append(cid)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE companies SET {sets}, updated_at = NOW() WHERE id = %s", vals)
        log.info(f"  Updated company: {list(updates.keys())}")
    
    # Find and parse project pages
    project_urls = find_project_pages(website, html)
    log.info(f"  Found {len(project_urls)} potential project pages")
    
    all_projects = parse_projects_from_page(html, website, name)
    
    for purl in project_urls[:5]:
        time.sleep(1)
        phtml = fetch_page(purl)
        if phtml:
            projs = parse_projects_from_page(phtml, purl, name)
            all_projects.extend(projs)
    
    # Deduplicate by area
    seen_areas = set()
    unique_projects = []
    for p in all_projects:
        key = f"{p['area']:.0f}_{p['material']}"
        if key not in seen_areas:
            seen_areas.add(key)
            unique_projects.append(p)
    
    # Insert projects
    inserted = 0
    for proj in unique_projects:
        with conn.cursor() as cur:
            # Check if similar project exists
            cur.execute("""
                SELECT id FROM projects 
                WHERE company_id = %s AND ABS(area - %s) < 1 AND material = %s
            """, (cid, proj['area'], proj['material']))
            if cur.fetchone():
                continue
            
            cur.execute("""
                INSERT INTO projects (company_id, name, area, floors, material, price, 
                                     description, url, source, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (cid, proj['name'], proj['area'], proj['floors'], proj['material'],
                  proj['price'], proj.get('description'), proj['url'], 
                  proj['source'], proj['source_url']))
            inserted += 1
    
    if inserted:
        # Update projects_count
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE companies SET projects_count = (
                    SELECT COUNT(*) FROM projects WHERE company_id = %s
                ) WHERE id = %s
            """, (cid, cid))
        log.info(f"  Inserted {inserted} projects")
    
    return inserted

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else 'Ленинградская область'
    log.info(f"=== Starting enrichment for {region} ===")
    
    conn = get_db()
    
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, website, phone, email, description, 
                   price_per_sqm_min, rating, reviews_count
            FROM companies 
            WHERE region = %s AND website IS NOT NULL AND website != ''
            ORDER BY rating DESC NULLS LAST, name
        """, (region,))
        companies = cur.fetchall()
    
    log.info(f"Found {len(companies)} companies with websites in {region}")
    
    total_projects = 0
    enriched = 0
    errors = 0
    
    for i, company in enumerate(companies):
        try:
            n = enrich_company(conn, company)
            total_projects += n
            enriched += 1
            log.info(f"  [{i+1}/{len(companies)}] {company['name']}: {n} projects")
        except Exception as e:
            errors += 1
            log.error(f"  Error with {company['name']}: {e}")
        
        time.sleep(2)  # Be polite
    
    log.info(f"=== DONE: {enriched} companies enriched, {total_projects} new projects, {errors} errors ===")

if __name__ == '__main__':
    main()
