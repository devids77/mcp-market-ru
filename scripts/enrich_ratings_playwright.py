#!/usr/bin/env python3
"""
Enrich company ratings from 2GIS using Playwright headless browser.
Searches each company on 2GIS, extracts general_rating and general_review_count.
"""
import os, sys, re, time, json, random, logging
import psycopg2
from urllib.parse import quote
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/mcp-market/enrich_ratings_pw.log')
    ]
)
log = logging.getLogger(__name__)

DB = "postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket"

def get_companies(region=None):
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    q = """SELECT id, name, city FROM companies 
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
    log.info(f"Found {len(rows)} companies without ratings (region={region})")
    return rows

def save_rating(cid, rating, reviews_count, source="2gis_playwright"):
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    if reviews_count and reviews_count > 0:
        cur.execute("""UPDATE companies 
                       SET rating=%s, rating_source=%s, 
                           reviews_count=GREATEST(COALESCE(reviews_count,0),%s),
                           updated_at=NOW() 
                       WHERE id=%s""",
                    (rating, source, reviews_count, cid))
    else:
        cur.execute("""UPDATE companies 
                       SET rating=%s, rating_source=%s, updated_at=NOW() 
                       WHERE id=%s""",
                    (rating, source, cid))
    conn.commit()
    cur.close()
    conn.close()

def extract_ratings_from_content(content, company_name):
    """Extract rating data from 2GIS page content.
    Returns list of (name_snippet, rating, review_count) tuples."""
    results = []
    
    # Pattern 1: Look for general_rating near company data
    # Format: "general_rating":N,"general_review_count":N
    for m in re.finditer(r'"general_rating":\s*([\d.]+)\s*,\s*"general_review_count":\s*(\d+)', content):
        rating = float(m.group(1))
        reviews = int(m.group(2))
        # Get surrounding context to find company name
        start = max(0, m.start() - 500)
        ctx = content[start:m.start()]
        # Look for name in context
        name_m = re.findall(r'"name":\s*"([^"]+)"', ctx)
        name = name_m[-1] if name_m else "unknown"
        if 1.0 <= rating <= 5.0:
            results.append((name, rating, reviews))
    
    # Pattern 2: Try alternative format "rating":{"value":N}
    if not results:
        for m in re.finditer(r'"rating":\s*\{\s*"value":\s*([\d.]+)', content):
            rating = float(m.group(1))
            start = max(0, m.start() - 500)
            ctx = content[start:m.start()]
            name_m = re.findall(r'"name":\s*"([^"]+)"', ctx)
            name = name_m[-1] if name_m else "unknown"
            reviews_m = re.search(r'"review_count":\s*(\d+)', content[m.start():m.start()+200])
            reviews = int(reviews_m.group(1)) if reviews_m else 0
            if 1.0 <= rating <= 5.0:
                results.append((name, rating, reviews))
    
    return results

def fuzzy_match(name1, name2):
    """Simple fuzzy matching - check if key words overlap."""
    def normalize(s):
        s = s.lower().strip()
        # Remove common words
        for w in ['ооо', 'ао', 'зао', 'ип', 'ск', 'гк', 'пск', 'компания', 
                   'строительная', 'группа', '"', "'", '«', '»']:
            s = s.replace(w, '')
        return set(s.split())
    
    words1 = normalize(name1)
    words2 = normalize(name2)
    if not words1 or not words2:
        return False
    # Check overlap
    common = words1 & words2
    return len(common) >= 1 and len(common) / min(len(words1), len(words2)) >= 0.5

def search_company_2gis(page, company_name, city="Санкт-Петербург"):
    """Search for a company on 2GIS and return (rating, review_count) or None."""
    # Determine 2GIS city slug
    city_slugs = {
        "Санкт-Петербург": "spb",
        "Ленинградская область": "spb",
        "Москва": "moscow",
        "Московская область": "moscow",
        "Новосибирск": "novosibirsk",
        "Новосибирская область": "novosibirsk",
        "Екатеринбург": "ekaterinburg",
        "Свердловская область": "ekaterinburg",
        "Краснодар": "krasnodar",
        "Краснодарский край": "krasnodar",
        "Красноярск": "krasnoyarsk",
        "Красноярский край": "krasnoyarsk",
        "Тюмень": "tyumen",
        "Тюменская область": "tyumen",
        "Уфа": "ufa",
        "Республика Башкортостан": "ufa",
        "Казань": "kazan",
        "Республика Татарстан": "kazan",
        "Самара": "samara",
        "Самарская область": "samara",
        "Воронеж": "voronezh",
        "Воронежская область": "voronezh",
        "Челябинск": "chelyabinsk",
        "Челябинская область": "chelyabinsk",
        "Ростов-на-Дону": "rostovnd",
        "Ростовская область": "rostovnd",
        "Пермь": "perm",
        "Пермский край": "perm",
        "Волгоград": "volgograd",
        "Волгоградская область": "volgograd",
        "Нижний Новгород": "n_novgorod",
        "Нижегородская область": "n_novgorod",
        "Омск": "omsk",
        "Омская область": "omsk",
        "Иркутск": "irkutsk",
        "Иркутская область": "irkutsk",
    }
    slug = "spb"  # default
    for c, s in city_slugs.items():
        if city and c.lower() in city.lower():
            slug = s
            break
    
    search_query = quote(company_name)
    url = f"https://2gis.ru/{slug}/search/{search_query}"
    
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"  goto timeout (non-fatal): {e}")
    
    # Wait for content to render
    page.wait_for_timeout(6000)
    
    try:
        content = page.content()
    except:
        page.wait_for_timeout(3000)
        try:
            content = page.content()
        except Exception as e:
            log.error(f"  Failed to get content: {e}")
            return None
    
    log.info(f"  Page loaded: {len(content)} bytes")
    
    # Extract all ratings from the page
    results = extract_ratings_from_content(content, company_name)
    
    if not results:
        log.info(f"  No ratings found on page")
        return None
    
    log.info(f"  Found {len(results)} rated entries on page")
    
    # Try to find best match by name
    best_match = None
    for name, rating, reviews in results:
        if fuzzy_match(company_name, name):
            best_match = (rating, reviews, name)
            log.info(f"  MATCH: '{name}' -> rating={rating}, reviews={reviews}")
            break
    
    # If no fuzzy match, take first result (most relevant in search)
    if not best_match and len(results) == 1:
        name, rating, reviews = results[0]
        best_match = (rating, reviews, name)
        log.info(f"  Single result: '{name}' -> rating={rating}, reviews={reviews}")
    
    if not best_match and results:
        # Log all found for debugging
        for name, rating, reviews in results[:3]:
            log.info(f"  Found but no match: '{name}' rating={rating}")
    
    return best_match

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else "Ленинградская область"
    companies = get_companies(region)
    
    if not companies:
        log.info("No companies to process")
        return
    
    found = 0
    errors = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, 
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ru-RU'
        )
        page = context.new_page()
        
        for i, (cid, name, city) in enumerate(companies):
            log.info(f"\n[{i+1}/{len(companies)}] Processing: {name} (id={cid}, city={city})")
            
            try:
                result = search_company_2gis(page, name, city or region)
                
                if result:
                    rating, reviews, matched_name = result
                    save_rating(cid, rating, reviews)
                    found += 1
                    log.info(f"  SAVED: rating={rating}, reviews={reviews}")
                else:
                    log.info(f"  No rating found")
                
            except Exception as e:
                log.error(f"  Error: {e}")
                errors += 1
                # Recreate page on error
                try:
                    page.close()
                except:
                    pass
                page = context.new_page()
            
            # Rate limiting: 5-10 seconds between requests
            delay = random.uniform(5, 10)
            log.info(f"  Waiting {delay:.1f}s...")
            time.sleep(delay)
            
            # Progress report every 10 companies
            if (i + 1) % 10 == 0:
                log.info(f"\n=== PROGRESS: {i+1}/{len(companies)} processed, {found} found, {errors} errors ===\n")
        
        browser.close()
    
    log.info(f"\n{'='*50}")
    log.info(f"COMPLETE: {len(companies)} processed, {found} ratings found, {errors} errors")
    log.info(f"{'='*50}")

if __name__ == "__main__":
    main()
