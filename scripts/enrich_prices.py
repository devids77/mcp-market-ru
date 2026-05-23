#!/usr/bin/env python3
"""Enrich price data from company websites - extract price per sqm from web pages."""
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import urllib.request
import ssl
import time

DB = "postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket"

def extract_prices(html):
    """Extract price per sqm from HTML content."""
    prices = []
    # Common patterns for prices per sqm in Russian construction sites
    patterns = [
        r'(\d[\d\s]*\d)\s*(?:руб|₽|р\.?)\s*(?:/|за)\s*(?:м[²2]|кв\.?\s*м)',
        r'(?:от|from)\s*(\d[\d\s]*\d)\s*(?:руб|₽|р\.?)',
        r'(?:цена|стоимость|price)[\s:]*(\d[\d\s]*\d)\s*(?:руб|₽|р)',
        r'(\d[\d\s]*\d)\s*(?:руб|₽|р\.?)\s*/\s*м',
        r'(\d{2,6})\s*₽/м²',
        r'(\d{2,6})\s*руб/м2',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for m in matches:
            try:
                price = int(re.sub(r'\s+', '', m))
                # Reasonable price per sqm: 5000-500000 rubles
                if 5000 <= price <= 500000:
                    prices.append(price)
            except:
                continue
    
    # Also try to find project prices (min project cost)
    project_prices = []
    proj_patterns = [
        r'(?:от|from)\s*(\d[\d\s]*\d)\s*(?:000)?\s*(?:руб|₽|р)',
        r'(?:минимальн|стоимость проекта|цена дома)[\s:]*(\d[\d\s]*\d)\s*(?:руб|₽|р)',
    ]
    for pattern in proj_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for m in matches:
            try:
                price = int(re.sub(r'\s+', '', m))
                if 100000 <= price <= 50000000:
                    project_prices.append(price)
            except:
                continue
    
    return prices, project_prices

def fetch_url(url, timeout=10):
    """Fetch URL content."""
    try:
        if not url.startswith('http'):
            url = 'https://' + url
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; MCPBot/1.0)',
            'Accept': 'text/html',
            'Accept-Language': 'ru-RU,ru;q=0.9',
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except:
        return None

def main():
    conn = psycopg2.connect(DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get companies with websites but no prices, ordered by rating
    cur.execute("""
        SELECT id, slug, name, website, region, category
        FROM companies 
        WHERE website IS NOT NULL 
          AND price_per_sqm_min IS NULL
          AND rating > 0
        ORDER BY reviews_count DESC, rating DESC
        LIMIT 500
    """)
    companies = cur.fetchall()
    print(f"Found {len(companies)} companies to process")
    
    updated = 0
    errors = 0
    
    for i, company in enumerate(companies):
        try:
            html = fetch_url(company['website'])
            if not html:
                errors += 1
                continue
            
            sqm_prices, project_prices = extract_prices(html)
            
            if sqm_prices:
                min_price = min(sqm_prices)
                max_price = max(sqm_prices)
                
                update_fields = ["price_per_sqm_min = %s", "price_per_sqm_max = %s"]
                update_values = [min_price, max_price]
                
                if project_prices:
                    update_fields.append("min_project_price = %s")
                    update_values.append(min(project_prices))
                
                update_values.append(company['id'])
                
                cur.execute(f"""
                    UPDATE companies SET {', '.join(update_fields)}
                    WHERE id = %s
                """, update_values)
                conn.commit()
                updated += 1
                print(f"[{i+1}/{len(companies)}] {company['slug']}: {min_price}-{max_price} ₽/m²")
            
            if (i+1) % 50 == 0:
                print(f"Progress: {i+1}/{len(companies)}, updated: {updated}, errors: {errors}")
            
            time.sleep(0.5)  # Be polite
            
        except Exception as e:
            errors += 1
            if (i+1) % 100 == 0:
                print(f"Error on {company['slug']}: {e}")
            continue
    
    cur.close()
    conn.close()
    print(f"\nDone! Updated: {updated}, Errors: {errors}, Total processed: {len(companies)}")

if __name__ == '__main__':
    main()
