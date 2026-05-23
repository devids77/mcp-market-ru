#!/usr/bin/env python3
"""
Multi-source ratings enrichment for MCP Market companies.
Sources: 2GIS web, Flamp.ru, Zoon.ru, company websites
Slow and steady - respects rate limits.
"""
import os, sys, re, time, json, random, logging
import httpx
import psycopg2
from urllib.parse import quote_plus, urljoin

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_CONN = f"postgresql://{os.getenv('DB_USER','mcpuser')}:{os.getenv('DB_PASS','McpMarket2026Secure')}@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','mcpmarket')}"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
}

DELAY_MIN = 3
DELAY_MAX = 7

def get_companies(region=None):
    """Get companies without rating from DB."""
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()
    q = """SELECT id, name, city, website FROM companies 
           WHERE (rating IS NULL OR rating = 0)"""
    params = []
    if region:
        q += " AND region = %s"
        params.append(region)
    q += " ORDER BY id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_rating(company_id, rating, source, reviews_count=None):
    """Update company rating in DB."""
    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()
    if reviews_count and reviews_count > 0:
        cur.execute("""UPDATE companies SET rating = %s, rating_source = %s, reviews_count = GREATEST(COALESCE(reviews_count,0), %s), updated_at = NOW() WHERE id = %s""",
                    (rating, source, reviews_count, company_id))
    else:
        cur.execute("""UPDATE companies SET rating = %s, rating_source = %s, updated_at = NOW() WHERE id = %s""",
                    (rating, source, company_id))
    conn.commit()
    cur.close()
    conn.close()
    log.info(f"  => Updated id={company_id}: rating={rating} source={source} reviews={reviews_count}")

def fetch(url, timeout=15):
    """Fetch URL with retry."""
    for attempt in range(2):
        try:
            r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            log.warning(f"  HTTP {r.status_code} for {url[:80]}")
            return None
        except Exception as e:
            log.warning(f"  Fetch error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return None

def search_2gis_web(company_name, city="Санкт-Петербург"):
    """Search 2GIS website for company rating."""
    try:
        city_slug = "saint_petersburg" if "Петербург" in city else "leningradskaya_oblast"
        query = quote_plus(f"{company_name}")
        url = f"https://2gis.ru/{city_slug}/search/{query}"
        html = fetch(url)
        if not html:
            return None
        
        # Look for rating in JSON-LD or structured data
        # 2GIS embeds rating data in script tags
        rating_patterns = [
            r'"rating"\s*:\s*{\s*"value"\s*:\s*([\d.]+)',
            r'"ratingValue"\s*:\s*"?([\d.]+)',
            r'class="[^"]*rating[^"]*"[^>]*>([\d.,]+)',
            r'data-rating="([\d.]+)"',
            r'"general_rating"\s*:\s*([\d.]+)',
            r'"rating":\s*([\d.]+)',
        ]
        reviews_patterns = [
            r'"general_review_count"\s*:\s*(\d+)',
            r'"reviewCount"\s*:\s*"?(\d+)',
            r'(\d+)\s*(?:отзыв|review)',
        ]
        
        rating = None
        reviews = None
        for pat in rating_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if 1.0 <= val <= 5.0:
                        rating = round(val, 1)
                        break
                except:
                    continue
        
        for pat in reviews_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    reviews = int(m.group(1))
                    break
                except:
                    continue
        
        if rating:
            return {'rating': rating, 'reviews': reviews, 'source': '2gis'}
    except Exception as e:
        log.warning(f"  2GIS error: {e}")
    return None

def search_flamp(company_name, city="Санкт-Петербург"):
    """Search Flamp.ru for company rating."""
    try:
        query = quote_plus(f"{company_name} {city}")
        url = f"https://spb.flamp.ru/search?query={query}"
        html = fetch(url)
        if not html:
            return None
        
        # Flamp uses structured rating data
        rating_patterns = [
            r'"ratingValue"\s*:\s*"?([\d.]+)',
            r'class="[^"]*rating-value[^"]*"[^>]*>([\d.,]+)',
            r'data-rating="([\d.]+)"',
            r'rating.*?([\d]\.\d)',
        ]
        reviews_patterns = [
            r'"reviewCount"\s*:\s*"?(\d+)',
            r'(\d+)\s*отзыв',
        ]
        
        rating = None
        reviews = None
        for pat in rating_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if 1.0 <= val <= 5.0:
                        rating = round(val, 1)
                        break
                except:
                    continue
        
        for pat in reviews_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    reviews = int(m.group(1))
                    break
                except:
                    continue
        
        if rating:
            return {'rating': rating, 'reviews': reviews, 'source': 'flamp'}
    except Exception as e:
        log.warning(f"  Flamp error: {e}")
    return None

def search_zoon(company_name, city="Санкт-Петербург"):
    """Search Zoon.ru for company rating."""
    try:
        query = quote_plus(f"{company_name}")
        url = f"https://zoon.ru/spb/search/?search_query={query}&type=service"
        html = fetch(url)
        if not html:
            return None
        
        rating_patterns = [
            r'"ratingValue"\s*:\s*"?([\d.]+)',
            r'class="[^"]*z-text--rating[^"]*"[^>]*>([\d.,]+)',
            r'itemprop="ratingValue"[^>]*content="([\d.]+)"',
        ]
        reviews_patterns = [
            r'"reviewCount"\s*:\s*"?(\d+)',
            r'(\d+)\s*отзыв',
        ]
        
        rating = None
        reviews = None
        for pat in rating_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if 1.0 <= val <= 5.0:
                        rating = round(val, 1)
                        break
                except:
                    continue
        
        for pat in reviews_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    reviews = int(m.group(1))
                    break
                except:
                    continue
        
        if rating:
            return {'rating': rating, 'reviews': reviews, 'source': 'zoon'}
    except Exception as e:
        log.warning(f"  Zoon error: {e}")
    return None

def search_yell(company_name, city="Санкт-Петербург"):
    """Search Yell.ru for company rating."""
    try:
        query = quote_plus(f"{company_name} {city}")
        url = f"https://www.yell.ru/search/?text={query}"
        html = fetch(url)
        if not html:
            return None
        
        rating_patterns = [
            r'"ratingValue"\s*:\s*"?([\d.]+)',
            r'class="[^"]*rating[^"]*"[^>]*>\s*([\d.,]+)',
        ]
        reviews_patterns = [
            r'"reviewCount"\s*:\s*"?(\d+)',
            r'(\d+)\s*отзыв',
        ]
        
        rating = None
        reviews = None
        for pat in rating_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if 1.0 <= val <= 5.0:
                        rating = round(val, 1)
                        break
                except:
                    continue
        
        for pat in reviews_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    reviews = int(m.group(1))
                    break
                except:
                    continue
        
        if rating:
            return {'rating': rating, 'reviews': reviews, 'source': 'yell'}
    except Exception as e:
        log.warning(f"  Yell error: {e}")
    return None

def search_website_rating(website):
    """Try to extract rating from company's own website."""
    if not website:
        return None
    try:
        html = fetch(website)
        if not html:
            return None
        
        # Look for schema.org rating
        patterns = [
            r'"ratingValue"\s*:\s*"?([\d.]+)',
            r'itemprop="ratingValue"[^>]*content="([\d.]+)"',
            r'"aggregateRating".*?"ratingValue"\s*:\s*"?([\d.]+)',
        ]
        reviews_patterns = [
            r'"reviewCount"\s*:\s*"?(\d+)',
            r'"ratingCount"\s*:\s*"?(\d+)',
        ]
        
        rating = None
        reviews = None
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                try:
                    val = float(m.group(1).replace(',', '.'))
                    if 1.0 <= val <= 5.0:
                        rating = round(val, 1)
                        break
                except:
                    continue
        
        for pat in reviews_patterns:
            m = re.search(pat, html)
            if m:
                try:
                    reviews = int(m.group(1))
                    break
                except:
                    continue
        
        if rating:
            return {'rating': rating, 'reviews': reviews, 'source': 'website'}
    except Exception as e:
        log.warning(f"  Website rating error: {e}")
    return None

def process_company(cid, name, city, website):
    """Try all sources for a company rating."""
    city = city or "Санкт-Петербург"
    log.info(f"Processing [{cid}] {name} ({city})")
    
    # Source 1: 2GIS web
    result = search_2gis_web(name, city)
    if result:
        log.info(f"  Found on 2GIS: {result['rating']} ({result.get('reviews',0)} reviews)")
        update_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    # Source 2: Flamp
    result = search_flamp(name, city)
    if result:
        log.info(f"  Found on Flamp: {result['rating']} ({result.get('reviews',0)} reviews)")
        update_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    # Source 3: Zoon
    result = search_zoon(name, city)
    if result:
        log.info(f"  Found on Zoon: {result['rating']} ({result.get('reviews',0)} reviews)")
        update_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    
    # Source 4: Yell
    result = search_yell(name, city)
    if result:
        log.info(f"  Found on Yell: {result['rating']} ({result.get('reviews',0)} reviews)")
        update_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    time.sleep(random.uniform(2, 4))
    
    # Source 5: Company website (schema.org)
    if website:
        result = search_website_rating(website)
        if result:
            log.info(f"  Found on website: {result['rating']} ({result.get('reviews',0)} reviews)")
            update_rating(cid, result['rating'], result['source'], result.get('reviews'))
            return result['source']
    
    log.info(f"  No rating found from any source")
    return None

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else None
    log.info(f"=== Multi-source ratings enrichment ===")
    log.info(f"Region filter: {region or 'ALL'}")
    
    companies = get_companies(region)
    log.info(f"Companies without rating: {len(companies)}")
    
    stats = {'total': len(companies), 'found': 0, 'sources': {}}
    
    for i, (cid, name, city, website) in enumerate(companies):
        log.info(f"--- [{i+1}/{len(companies)}] ---")
        source = process_company(cid, name, city, website)
        if source:
            stats['found'] += 1
            stats['sources'][source] = stats['sources'].get(source, 0) + 1
        
        # Rate limiting between companies
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        log.info(f"  Sleeping {delay:.1f}s...")
        time.sleep(delay)
    
    log.info(f"\n=== RESULTS ===")
    log.info(f"Total processed: {stats['total']}")
    log.info(f"Ratings found: {stats['found']}")
    log.info(f"By source: {json.dumps(stats['sources'], ensure_ascii=False)}")
    log.info(f"Not found: {stats['total'] - stats['found']}")

if __name__ == '__main__':
    main()
