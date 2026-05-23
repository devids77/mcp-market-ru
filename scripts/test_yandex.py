#!/usr/bin/env python3
"""Test Yandex Maps rating extraction"""
import re
from playwright.sync_api import sync_playwright
from urllib.parse import quote

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
    ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36', viewport={'width':1920,'height':1080}, locale='ru-RU', timezone_id='Europe/Moscow')
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = ctx.new_page()
    
    q = quote("Гамма септик Санкт-Петербург")
    url = f"https://yandex.ru/maps/?text={q}"
    print(f"Loading: {url}")
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"goto: {e}")
    page.wait_for_timeout(8000)
    
    content = page.content()
    print(f"Content: {len(content)} bytes")
    
    if 'captcha' in content.lower() or 'SmartCaptcha' in content:
        print("CAPTCHA DETECTED!")
    else:
        print("No CAPTCHA")
    
    # Search for rating patterns
    print("\n=== RATING PATTERNS ===")
    for pat_name, pat in [
        ("ratingValue", r'"ratingValue"\s*:\s*"?([\d.]+)'),
        ("rating_value", r'"rating"\s*:\s*\{\s*"value"\s*:\s*([\d.]+)'),
        ("stars", r'"stars"\s*:\s*([\d.]+)'),
        ("averageRating", r'"averageRating"\s*:\s*([\d.]+)'),
        ("score_class", r'(?:rating|score)[^>]*>\s*([\d][.,]\d)\s*<'),
        ("aria_rating", r'aria-label="[^"]*?(\d[.,]\d)\s*(?:из|/)\s*5'),
        ("orgRating", r'"orgRating"\s*:\s*([\d.]+)'),
        ("rating_num", r'class="[^"]*rating[^"]*"[^>]*>\s*([\d][.,]\d)'),
    ]:
        matches = re.findall(pat, content)
        if matches:
            print(f"  {pat_name}: {matches[:5]}")
    
    # Context around "rating" word
    print("\n=== RATING WORD CONTEXTS (first 5) ===")
    cnt = 0
    for m in re.finditer(r'rating', content, re.I):
        start = max(0, m.start()-60)
        end = min(len(content), m.end()+60)
        c = content[start:end].replace('\n',' ')
        print(f"  [{m.start()}] {c}")
        cnt += 1
        if cnt >= 5:
            break
    
    # Check for review/отзыв
    print("\n=== REVIEW CONTEXTS (first 5) ===")
    cnt = 0
    for m in re.finditer(r'отзыв', content, re.I):
        start = max(0, m.start()-60)
        end = min(len(content), m.end()+60)
        c = content[start:end].replace('\n',' ')
        print(f"  [{m.start()}] {c}")
        cnt += 1
        if cnt >= 5:
            break
    
    browser.close()
    print("\nDONE")
