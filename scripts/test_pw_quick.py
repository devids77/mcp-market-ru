#!/usr/bin/env python3
"""Quick test: search 3 specific companies on 2GIS"""
import re
from playwright.sync_api import sync_playwright
from urllib.parse import quote
import psycopg2

DB = "postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@localhost:5432/mcpmarket"
conn = psycopg2.connect(DB)
cur = conn.cursor()
cur.execute("""SELECT id, name, city FROM companies 
               WHERE (rating IS NULL OR rating = 0) AND region='Ленинградская область' 
               ORDER BY id LIMIT 5""")
companies = cur.fetchall()
cur.close(); conn.close()
print(f"Testing {len(companies)} companies:")
for c in companies:
    print(f"  id={c[0]}, name='{c[1]}', city='{c[2]}'")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
    page = browser.new_page(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
    
    for cid, name, city in companies:
        print(f"\n--- Searching: {name} ---")
        sq = quote(name)
        url = f"https://2gis.ru/spb/search/{sq}"
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
        except:
            pass
        page.wait_for_timeout(7000)
        try:
            content = page.content()
        except:
            page.wait_for_timeout(3000)
            content = page.content()
        print(f"  Content: {len(content)} bytes")
        
        # Extract ratings
        ratings = []
        for m in re.finditer(r'"general_rating":\s*([\d.]+)\s*,\s*"general_review_count":\s*(\d+)', content):
            r, rv = float(m.group(1)), int(m.group(2))
            start = max(0, m.start()-500)
            ctx = content[start:m.start()]
            nm = re.findall(r'"name":\s*"([^"]+)"', ctx)
            n = nm[-1] if nm else "?"
            ratings.append((n, r, rv))
            print(f"  Found: '{n}' rating={r} reviews={rv}")
        
        if not ratings:
            print("  No ratings found, checking alt patterns...")
            alt = re.findall(r'"general_rating":\s*([\d.]+)', content)
            print(f"  Alt general_rating matches: {alt[:5]}")
        
        import time; time.sleep(3)
    
    browser.close()
    print("\nDONE")
