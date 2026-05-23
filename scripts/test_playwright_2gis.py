#!/usr/bin/env python3
"""Test Playwright with 2GIS - extract company ratings"""
import re, json
from playwright.sync_api import sync_playwright

def test_2gis():
    print("Starting Playwright test for 2GIS...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
        
        # Test 1: Search for construction companies in SPb
        url = "https://2gis.ru/spb/search/%D0%A1%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%B0%D1%8F%20%D0%BA%D0%BE%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F"
        print(f"Loading: {url}")
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        content = page.content()
        print(f"Page loaded, content length: {len(content)}")
        
        # Try to extract ratings from JSON in page
        # 2GIS embeds data as JSON in script tags
        scripts = page.query_selector_all('script')
        print(f"Found {len(scripts)} script tags")
        
        # Look for rating data in page content
        rating_matches = re.findall(r'"rating":\s*\{"value":\s*([\d.]+)', content)
        review_matches = re.findall(r'"general_review_count(?:_text)?":\s*["\']?(\d+)', content)
        name_matches = re.findall(r'"name":\s*"([^"]{5,80})"', content)
        
        print(f"\nResults:")
        print(f"  Rating values found: {len(rating_matches)}")
        print(f"  Review counts found: {len(review_matches)}")
        print(f"  Company names found: {len(name_matches)}")
        
        if rating_matches:
            print(f"\n  Sample ratings: {rating_matches[:10]}")
        if review_matches:
            print(f"  Sample review counts: {review_matches[:10]}")
        if name_matches:
            unique_names = list(dict.fromkeys(name_matches))[:10]
            print(f"  Sample names: {unique_names}")
        
        # Test 2: Search for a specific company
        print("\n--- Test 2: Specific company search ---")
        page2 = browser.new_page(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
        page2.goto("https://2gis.ru/spb/search/ПСК%20Дом", timeout=60000, wait_until="domcontentloaded")
        page2.wait_for_timeout(5000)
        content2 = page2.content()
        print(f"Page loaded, content length: {len(content2)}")
        
        ratings2 = re.findall(r'"rating":\s*\{"value":\s*([\d.]+)', content2)
        names2 = re.findall(r'"name":\s*"([^"]{5,80})"', content2)
        print(f"  Ratings: {ratings2[:5]}")
        print(f"  Names: {names2[:5]}")
        
        browser.close()
        print("\nPlaywright 2GIS test complete!")

if __name__ == "__main__":
    test_2gis()
