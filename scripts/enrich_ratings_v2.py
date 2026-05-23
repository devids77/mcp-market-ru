#!/usr/bin/env python3
"""
Ratings enrichment v2 - uses working sources only:
1. Company website schema.org (AggregateRating)
2. Google search snippets (rating extraction from text)
3. DuckDuckGo search snippets
"""
import os, sys, re, time, json, random, logging
import httpx
import psycopg2
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

DB = f"postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket"

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
HEADERS = {'User-Agent': UA, 'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5'}

def get_companies(region=None):
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    q = "SELECT id, name, city, website FROM companies WHERE (rating IS NULL OR rating = 0)"
    params = []
    if region:
        q += " AND region = %s"
        params.append(region)
    q += " ORDER BY id"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def save_rating(cid, rating, source, reviews=None):
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    if reviews and reviews > 0:
        cur.execute("UPDATE companies SET rating=%s, rating_source=%s, reviews_count=GREATEST(COALESCE(reviews_count,0),%s), updated_at=NOW() WHERE id=%s",
                    (rating, source, reviews, cid))
    else:
        cur.execute("UPDATE companies SET rating=%s, rating_source=%s, updated_at=NOW() WHERE id=%s",
                    (rating, source, cid))
    conn.commit(); cur.close(); conn.close()
    log.info(f"  => SAVED rating={rating} source={source} reviews={reviews}")

def fetch(url, timeout=12):
    for attempt in range(2):
        try:
            r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            return None
        except:
            time.sleep(1)
    return None

def extract_rating(text):
    """Extract rating value (1.0-5.0) from text using multiple patterns."""
    patterns = [
        r'"ratingValue"\s*:\s*"?([\d.]+)',
        r'itemprop="ratingValue"[^>]*content="([\d.]+)"',
        r'"aggregateRating"[^}]*"ratingValue"\s*:\s*"?([\d.]+)',
        r'(\d\.\d)\s*(?:из|/)\s*5',
        r'[Рр]ейтинг[:\s]*([\d]\.\d)',
        r'(\d\.\d)\s*★',
        r'>(\d\.\d)</span',
        r'data-rating="(\d\.\d)"',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                val = float(m.group(1).replace(',','.'))
                if 1.0 <= val <= 5.0:
                    return round(val, 1)
            except:
                continue
    return None

def extract_reviews(text):
    """Extract review count from text."""
    patterns = [
        r'"reviewCount"\s*:\s*"?(\d+)',
        r'"ratingCount"\s*:\s*"?(\d+)',
        r'(\d+)\s*отзыв',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return int(m.group(1))
            except:
                continue
    return None

def source_website(website):
    """Extract rating from company website schema.org data."""
    if not website:
        return None
    html = fetch(website)
    if not html:
        return None
    rating = extract_rating(html)
    if rating:
        reviews = extract_reviews(html)
        return {'rating': rating, 'reviews': reviews, 'source': 'website'}
    # Try /about or /otzyvy pages
    for path in ['/otzyvy', '/otzyvy/', '/reviews', '/reviews/']:
        try:
            sub_url = website.rstrip('/') + path
            html2 = fetch(sub_url, timeout=8)
            if html2:
                r2 = extract_rating(html2)
                if r2:
                    rev2 = extract_reviews(html2)
                    return {'rating': r2, 'reviews': rev2, 'source': 'website'}
        except:
            pass
    return None

def source_google(company_name, city):
    """Extract rating from Google search snippets."""
    q = f'{company_name} {city} отзывы рейтинг'
    try:
        r = httpx.get('https://www.google.com/search',
                      params={'q': q, 'hl': 'ru', 'num': 10},
                      headers=HEADERS, timeout=12, follow_redirects=True)
        if r.status_code != 200:
            return None
        html = r.text
        # Google sometimes includes rating in span or aria-label
        rating = extract_rating(html)
        if rating:
            reviews = extract_reviews(html)
            return {'rating': rating, 'reviews': reviews, 'source': 'google'}
        # Also try to find ratings in snippet text
        # Pattern: "4.5 из 5" or "рейтинг 4.2"
        snippets = re.findall(r'<span[^>]*>([^<]{10,200})</span>', html)
        for snippet in snippets:
            r_val = extract_rating(snippet)
            if r_val:
                rev = extract_reviews(snippet)
                return {'rating': r_val, 'reviews': rev, 'source': 'google'}
    except Exception as e:
        log.warning(f"  Google error: {e}")
    return None

def source_ddg(company_name, city):
    """Extract rating from DuckDuckGo search."""
    q = f'{company_name} {city} строительная компания отзывы рейтинг'
    try:
        r = httpx.get('https://lite.duckduckgo.com/lite/',
                      params={'q': q},
                      headers=HEADERS, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            return None
        html = r.text
        rating = extract_rating(html)
        if rating:
            reviews = extract_reviews(html)
            return {'rating': rating, 'reviews': reviews, 'source': 'ddg'}
        # Extract URLs of review pages to visit directly
        review_urls = re.findall(r'href="(https?://[^"]*(?:otzyvy|reviews|flamp|zoon|yell)[^"]*)"', html)
        for url in review_urls[:2]:
            try:
                page = fetch(url, timeout=8)
                if page:
                    r_val = extract_rating(page)
                    if r_val:
                        rev = extract_reviews(page)
                        return {'rating': r_val, 'reviews': rev, 'source': 'ddg_link'}
            except:
                pass
            time.sleep(1)
    except Exception as e:
        log.warning(f"  DDG error: {e}")
    return None

def process(cid, name, city, website):
    city = city or "Санкт-Петербург"
    log.info(f"[{cid}] {name} ({city})")
    
    # 1. Website schema.org
    result = source_website(website)
    if result:
        save_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    time.sleep(random.uniform(2, 4))
    
    # 2. Google search
    result = source_google(name, city)
    if result:
        save_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    time.sleep(random.uniform(3, 5))
    
    # 3. DuckDuckGo
    result = source_ddg(name, city)
    if result:
        save_rating(cid, result['rating'], result['source'], result.get('reviews'))
        return result['source']
    
    log.info(f"  No rating found")
    return None

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else None
    companies = get_companies(region)
    log.info(f"=== Ratings enrichment v2 | Region: {region or 'ALL'} | Companies: {len(companies)} ===")
    
    stats = {'total': len(companies), 'found': 0, 'src': {}}
    for i, (cid, name, city, website) in enumerate(companies):
        log.info(f"--- [{i+1}/{len(companies)}] ---")
        src = process(cid, name, city, website)
        if src:
            stats['found'] += 1
            stats['src'][src] = stats['src'].get(src, 0) + 1
        time.sleep(random.uniform(3, 6))
    
    log.info(f"\n=== DONE === Found: {stats['found']}/{stats['total']} | Sources: {json.dumps(stats['src'])}")

if __name__ == '__main__':
    main()
