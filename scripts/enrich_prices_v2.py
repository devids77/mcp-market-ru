#!/usr/bin/env python3
"""Enhanced price enrichment - handles full prices (85000 rub/m2) and thousands (85 tys)."""
import re, sys, time, logging, random, psycopg2
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@localhost:5432/mcpmarket'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self._skip = {'script','style','noscript'}
        self._in_skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in self._skip: self._in_skip += 1
    def handle_endtag(self, tag):
        if tag in self._skip: self._in_skip = max(0, self._in_skip-1)
    def handle_data(self, data):
        if not self._in_skip: self.text.append(data)
    def get_text(self):
        return ' '.join(self.text)

def fetch_page(url, timeout=15):
    try:
        req = Request(url, headers={'User-Agent': UA})
        with urlopen(req, timeout=timeout) as r:
            ct = r.headers.get('Content-Type','')
            if 'text/html' not in ct and 'text/plain' not in ct:
                return None
            data = r.read(500000)
            for enc in ['utf-8','cp1251','latin1']:
                try: return data.decode(enc)
                except: pass
    except Exception as e:
        log.debug(f"Fetch error {url}: {e}")
    return None

def extract_price_per_sqm(text):
    """Extract price per sqm in thousands of rubles. Handles both formats."""
    text = text.replace('\xa0', ' ')
    prices = []
    
    # Pattern 1: "от XX XXX руб/м²" or "XX XXX ₽/м²" - full price near /m2
    for m in re.finditer(r'(\d[\d\s]{0,12})\s*(?:руб|₽|р\.?)\s*[/за]\s*(?:м[²2]|кв)', text, re.I):
        raw = m.group(1).replace(' ','').replace('\t','')
        try:
            val = float(raw)
            if 10000 <= val <= 500000:  # Full price per sqm
                prices.append(val / 1000)
            elif 10 <= val <= 500:  # Already in thousands
                prices.append(val)
        except: pass
    
    # Pattern 2: "цена от XX тыс" or "стоимость XX тыс. руб/м²"
    for m in re.finditer(r'(?:цена|стоимость|от)\s*(\d[\d\s,\.]*)\s*(?:тыс|т\.)\s*(?:руб|₽|р)', text, re.I):
        raw = m.group(1).replace(' ','').replace(',','.')
        try:
            val = float(raw)
            if 10 <= val <= 500:
                prices.append(val)
        except: pass
    
    # Pattern 3: "XX XXX руб" near keywords like цена, стоимость, м2
    for m in re.finditer(r'(?:цена|стоимость|от|м[²2])\s{0,5}(\d[\d\s]{2,12})\s*(?:руб|₽|р\.)', text, re.I):
        raw = m.group(1).replace(' ','')
        try:
            val = float(raw)
            if 15000 <= val <= 500000:
                prices.append(val / 1000)
        except: pass

    # Pattern 4: Reverse - "XX XXX руб/м²" where number comes before unit
    for m in re.finditer(r'(\d{2,3})\s*(\d{3})\s*(?:руб|₽)', text, re.I):
        raw = m.group(1) + m.group(2)
        try:
            val = float(raw)
            if 15000 <= val <= 500000:
                prices.append(val / 1000)
        except: pass
    
    # Pattern 5: Simple "от XX тыс" without explicit currency
    for m in re.finditer(r'от\s+(\d{2,3})\s*тыс', text, re.I):
        try:
            val = float(m.group(1))
            if 10 <= val <= 500:
                prices.append(val)
        except: pass

    if prices:
        prices = [p for p in prices if 10 <= p <= 500]
        if prices:
            return min(prices), max(prices)
    return None, None

def find_price_pages(html, base_url):
    """Find links to price/cost pages."""
    keywords = ['цен', 'прайс', 'стоимость', 'price', 'тариф', 'калькулятор']
    links = set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
        href = m.group(1)
        href_lower = href.lower()
        if any(k in href_lower for k in keywords):
            if href.startswith('/'):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            if href.startswith('http'):
                links.add(href)
    # Also check link text
    for m in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I|re.S):
        href, text = m.group(1), m.group(2)
        text_clean = re.sub(r'<[^>]+>', '', text).lower()
        if any(k in text_clean for k in keywords):
            if href.startswith('/'):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            if href.startswith('http'):
                links.add(href)
    return list(links)[:5]

def enrich_company(conn, company):
    cid, name, website = company
    if not website:
        return False
    
    url = website if website.startswith('http') else f'https://{website}'
    
    # Fetch main page
    html = fetch_page(url)
    if not html:
        return False
    
    ext = TextExtractor()
    ext.feed(html)
    main_text = ext.get_text()
    
    min_p, max_p = extract_price_per_sqm(main_text)
    
    # If no price on main page, check price-specific pages
    if min_p is None:
        price_pages = find_price_pages(html, url)
        for pp in price_pages:
            time.sleep(random.uniform(1, 3))
            phtml = fetch_page(pp)
            if phtml:
                ext2 = TextExtractor()
                ext2.feed(phtml)
                ptext = ext2.get_text()
                min_p, max_p = extract_price_per_sqm(ptext)
                if min_p is not None:
                    log.info(f"  Found price on {pp}")
                    break
    
    # Also check project pages
    if min_p is None:
        proj_keywords = ['проект', 'объект', 'портфолио', 'наши-дома', 'каталог', 'дом']
        proj_links = set()
        for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
            href = m.group(1).lower()
            if any(k in href for k in proj_keywords):
                full = m.group(1)
                if full.startswith('/'):
                    from urllib.parse import urljoin
                    full = urljoin(url, full)
                if full.startswith('http'):
                    proj_links.add(full)
        for pl in list(proj_links)[:3]:
            time.sleep(random.uniform(1, 3))
            phtml = fetch_page(pl)
            if phtml:
                ext3 = TextExtractor()
                ext3.feed(phtml)
                min_p, max_p = extract_price_per_sqm(ext3.get_text())
                if min_p is not None:
                    log.info(f"  Found price on project page {pl}")
                    break
    
    if min_p is not None:
        cur = conn.cursor()
        cur.execute("""UPDATE companies SET price_per_sqm_min=%s, price_per_sqm_max=%s 
                       WHERE id=%s AND (price_per_sqm_min IS NULL)""",
                    (min_p, max_p, cid))
        conn.commit()
        log.info(f"  Updated prices: {min_p}-{max_p} тыс.руб/м²")
        return True
    return False

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else None
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    if region:
        cur.execute("""SELECT id, name, website FROM companies 
                       WHERE region=%s AND website IS NOT NULL AND price_per_sqm_min IS NULL
                       ORDER BY id""", (region,))
    else:
        cur.execute("""SELECT id, name, website FROM companies 
                       WHERE website IS NOT NULL AND price_per_sqm_min IS NULL
                       ORDER BY id""")
    
    companies = cur.fetchall()
    log.info(f"Found {len(companies)} companies without prices" + (f" in {region}" if region else ""))
    
    found = 0
    for i, company in enumerate(companies):
        try:
            if enrich_company(conn, company):
                found += 1
            log.info(f"  [{i+1}/{len(companies)}] {company[1]}: {'PRICE FOUND' if found > (found-1) else 'no price'}")
        except Exception as e:
            log.error(f"  Error with {company[1]}: {e}")
        time.sleep(random.uniform(2, 5))
    
    log.info(f"=== DONE: {found} prices found out of {len(companies)} companies ===")
    conn.close()

if __name__ == '__main__':
    main()
