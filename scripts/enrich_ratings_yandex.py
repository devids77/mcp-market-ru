#!/usr/bin/env python3
"""
Enrich company ratings from Yandex Maps using Playwright.
Runs AFTER 2GIS parser - only processes companies still without ratings.
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
        logging.FileHandler('/opt/mcp-market/enrich_ratings_yandex.log')
    ]
)
log = logging.getLogger(__name__)

DB = "postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@localhost:5432/mcpmarket"

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
    cur.close(); conn.close()
    log.info(f"Found {len(rows)} companies without ratings (region={region})")
    return rows

def save_rating(cid, rating, reviews_count, source="yandex_maps"):
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    if reviews_count and reviews_count > 0:
        cur.execute("""UPDATE companies SET rating=%s, rating_source=%s, 
                       reviews_count=GREATEST(COALESCE(reviews_count,0),%s),
                       updated_at=NOW() WHERE id=%s""",
                    (rating, source, reviews_count, cid))
    else:
        cur.execute("""UPDATE companies SET rating=%s, rating_source=%s, 
                       updated_at=NOW() WHERE id=%s""", (rating, source, cid))
    conn.commit(); cur.close(); conn.close()

def extract_yandex_rating(content):
    """Extract rating from Yandex Maps page content."""
    results = []
    
    # Pattern 1: og:description meta tag
    # "Рейтинг 4,3, 5 отзывов, 26 фото"
    og_m = re.search(r'<meta\s+property="og:description"\s+content="[^"]*?[Рр]ейтинг\s+([\d][.,]\d)\s*,\s*(\d+)\s*отзыв', content)
    if og_m:
        rating = float(og_m.group(1).replace(',','.'))
        reviews = int(og_m.group(2))
        if 1.0 <= rating <= 5.0:
            results.append(('og_description', rating, reviews))
    
    # Pattern 2: Schema.org ratingValue
    for m in re.finditer(r'"ratingValue"\s*:\s*"?([\d.]+)"?', content):
        rating = float(m.group(1))
        if 1.0 <= rating <= 5.0:
            rating = round(rating, 1)
            # Find reviewCount nearby
            ctx = content[m.start():min(len(content), m.end()+200)]
            rv = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', ctx)
            reviews = int(rv.group(1)) if rv else 0
            results.append(('schema_org', rating, reviews))
            break
    
    # Pattern 3: aria-label="Отзывы, N"
    aria_m = re.search(r'aria-label="[Оо]тзывы,?\s*(\d+)"', content)
    review_count_from_aria = int(aria_m.group(1)) if aria_m else 0
    
    # Pattern 4: CSS class with rating number display
    for m in re.finditer(r'class="[^"]*rating[^"]*"[^>]*>\s*([\d][.,]\d)\s*<', content):
        rating = float(m.group(1).replace(',','.'))
        if 1.0 <= rating <= 5.0:
            results.append(('html_rating', rating, review_count_from_aria))
            break
    
    # Pattern 5: Yandex internal JSON
    for m in re.finditer(r'"rating"\s*:\s*\{\s*"value"\s*:\s*([\d.]+)\s*,\s*"count"\s*:\s*(\d+)', content):
        rating = float(m.group(1))
        reviews = int(m.group(2))
        if 1.0 <= rating <= 5.0:
            results.append(('yandex_json', round(rating,1), reviews))
            break
    
    return results

def is_real_captcha(content):
    """Check if page has a real CAPTCHA (not just the word in JS bundles)."""
    # Real CAPTCHA pages are short and have specific elements
    if len(content) < 50000 and ('SmartCaptcha' in content or 'captcha__image' in content):
        return True
    if 'showcaptcha' in content.lower() and len(content) < 100000:
        return True
    return False

def search_yandex_maps(page, company_name, city="Санкт-Петербург"):
    """Search Yandex Maps for a company."""
    search_query = quote(f"{company_name} {city}")
    url = f"https://yandex.ru/maps/?text={search_query}"
    
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"  goto: {e}")
    
    page.wait_for_timeout(8000)
    
    try:
        content = page.content()
    except:
        page.wait_for_timeout(5000)
        try:
            content = page.content()
        except Exception as e:
            log.error(f"  Failed to get content: {e}")
            return None
    
    if is_real_captcha(content):
        log.warning(f"  CAPTCHA detected!")
        return 'CAPTCHA'
    
    log.info(f"  Page loaded: {len(content)} bytes")
    
    results = extract_yandex_rating(content)
    
    if not results:
        log.info(f"  No ratings found on Yandex Maps")
        return None
    
    source, rating, reviews = results[0]
    log.info(f"  Found: rating={rating}, reviews={reviews} (src={source})")
    return (rating, reviews, source)

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else "Ленинградская область"
    companies = get_companies(region)
    
    if not companies:
        log.info("No companies to process")
        return
    
    found = 0
    errors = 0
    captchas = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu',
                  '--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width':1920,'height':1080}, locale='ru-RU', timezone_id='Europe/Moscow'
        )
        context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = context.new_page()
        
        for i, (cid, name, city) in enumerate(companies):
            log.info(f"\n[{i+1}/{len(companies)}] {name} (id={cid}, city={city})")
            
            try:
                result = search_yandex_maps(page, name, city or "Санкт-Петербург")
                
                if result == 'CAPTCHA':
                    captchas += 1
                    if captchas >= 3:
                        log.error("Too many CAPTCHAs, stopping.")
                        break
                    time.sleep(random.uniform(30, 60))
                    continue
                
                if result:
                    rating, reviews, source = result
                    save_rating(cid, rating, reviews, f"yandex_{source}")
                    found += 1
                    log.info(f"  SAVED: rating={rating}, reviews={reviews}")
                
            except Exception as e:
                log.error(f"  Error: {e}")
                errors += 1
                try: page.close()
                except: pass
                page = context.new_page()
            
            delay = random.uniform(8, 15)
            log.info(f"  Waiting {delay:.1f}s...")
            time.sleep(delay)
            
            if (i+1) % 10 == 0:
                log.info(f"\n=== PROGRESS: {i+1}/{len(companies)}, {found} found, {captchas} captchas ===\n")
        
        browser.close()
    
    log.info(f"\n{'='*50}")
    log.info(f"COMPLETE: {len(companies)} processed, {found} found, {captchas} captchas, {errors} errors")

if __name__ == "__main__":
    main()
