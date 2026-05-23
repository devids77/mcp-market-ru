#!/usr/bin/env python3
"""Test Playwright 2GIS - robust version"""
import re
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
    page = browser.new_page(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
    url = "https://2gis.ru/spb/search/%D0%A1%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%B0%D1%8F%20%D0%BA%D0%BE%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F"
    print("Loading 2GIS...")
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"goto error (non-fatal): {e}")
    page.wait_for_timeout(8000)
    try:
        content = page.content()
    except:
        page.wait_for_timeout(5000)
        content = page.content()
    print(f"Content length: {len(content)}")
    ratings = re.findall(r'"rating":\s*\{[^}]*?"value":\s*([\d.]+)', content)
    reviews = re.findall(r'"review_count":\s*(\d+)', content)
    names = re.findall(r'"name":\s*"([^"]{5,80})"', content)
    print(f"Ratings: {len(ratings)} -> {ratings[:10]}")
    print(f"Reviews: {len(reviews)} -> {reviews[:10]}")
    unames = list(dict.fromkeys(names))[:10]
    print(f"Names: {len(names)} -> {unames}")
    # Also try direct API interception
    print("\n--- Checking for __initialState ---")
    state = re.findall(r'window\.__initialState__\s*=\s*', content)
    print(f"__initialState__ found: {len(state)}")
    # Check for catalog items
    items = re.findall(r'"type":\s*"branch"', content)
    print(f"Branch items: {len(items)}")
    browser.close()
    print("DONE")
