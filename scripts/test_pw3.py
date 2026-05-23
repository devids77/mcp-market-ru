#!/usr/bin/env python3
"""Investigate 2GIS HTML structure for rating data"""
import re
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
    page = browser.new_page(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
    url = "https://2gis.ru/spb/search/%D0%A1%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%B0%D1%8F%20%D0%BA%D0%BE%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F"
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    content = page.content()
    # Find all occurrences of "rating" in context
    print("=== RATING CONTEXTS ===")
    for m in re.finditer(r'rating', content):
        start = max(0, m.start()-80)
        end = min(len(content), m.end()+80)
        ctx = content[start:end].replace('\n',' ')
        print(f"[{m.start()}] ...{ctx}...")
        if m.start() > 50000:
            break
    print("\n=== REVIEW_COUNT CONTEXTS ===")
    for m in re.finditer(r'review.{0,5}count', content, re.I):
        start = max(0, m.start()-60)
        end = min(len(content), m.end()+60)
        ctx = content[start:end].replace('\n',' ')
        print(f"[{m.start()}] ...{ctx}...")
        if m.start() > 50000:
            break
    print("\n=== BRANCH TYPE CONTEXTS (first 3) ===")
    cnt = 0
    for m in re.finditer(r'"type":\s*"branch"', content):
        start = max(0, m.start()-200)
        end = min(len(content), m.end()+200)
        ctx = content[start:end].replace('\n',' ')
        print(f"[{m.start()}] ...{ctx}...")
        print("---")
        cnt += 1
        if cnt >= 3:
            break
    browser.close()
    print("DONE")
