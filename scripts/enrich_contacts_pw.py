#!/usr/bin/env python3
"""Enrich phone/email/website from 2GIS source_url pages using Playwright."""
import re, sys, time, logging, random, psycopg2
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket'

def extract_phone(text):
    """Extract phone number from text."""
    patterns = [
        r'(\+7\s*[\(\-]?\s*\d{3}\s*[\)\-]?\s*\d{3}[\-\s]?\d{2}[\-\s]?\d{2})',
        r'(8\s*[\(\-]?\s*\d{3}\s*[\)\-]?\s*\d{3}[\-\s]?\d{2}[\-\s]?\d{2})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None

def extract_email(text):
    m = re.search(r'[\w\.\-]+@[\w\.\-]+\.\w{2,}', text)
    return m.group(0) if m else None

def extract_website(text):
    m = re.search(r'(https?://[^\s<>"]+\.[a-z]{2,})', text, re.I)
    if m:
        url = m.group(1)
        if '2gis' not in url and 'yandex' not in url and 'google' not in url:
            return url
    return None

def scrape_2gis_page(page, url):
    """Scrape phone, email, website from 2GIS card page."""
    phone = email = website = None
    try:
        page.goto(url, wait_until='networkidle', timeout=20000)
        time.sleep(random.uniform(2, 4))
        
        content = page.content()
        text = page.inner_text('body')
        
        # Extract phone - look in specific elements
        try:
            phone_els = page.query_selector_all('[class*="phone"], a[href^="tel:"]')
            for el in phone_els:
                t = el.inner_text() or ''
                href = el.get_attribute('href') or ''
                p = extract_phone(t) or extract_phone(href.replace('tel:', ''))
                if p:
                    phone = p
                    break
        except: pass
        
        if not phone:
            phone = extract_phone(text)
        
        # Extract from href="tel:" in HTML
        if not phone:
            tel_match = re.search(r'href=["\']tel:([^"\']+)', content)
            if tel_match:
                phone = tel_match.group(1).strip()
        
        # Extract email
        email = extract_email(text)
        if not email:
            mail_match = re.search(r'href=["\']mailto:([^"\']+)', content)
            if mail_match:
                email = mail_match.group(1).strip()
        
        # Extract website
        try:
            site_els = page.query_selector_all('a[class*="website"], a[class*="link"]')
            for el in site_els:
                href = el.get_attribute('href') or ''
                if href and '2gis' not in href and 'yandex' not in href:
                    if re.match(r'https?://', href):
                        website = href
                        break
        except: pass
        
        if not website:
            website = extract_website(text)
        
    except Exception as e:
        log.debug(f"Error scraping {url}: {e}")
    
    return phone, email, website

def main():
    region = sys.argv[1] if len(sys.argv) > 1 else None
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    if region:
        cur.execute("""SELECT id, name, source_url, website FROM companies 
                       WHERE region=%s AND phone IS NULL AND source_url IS NOT NULL AND source_url LIKE '%%2gis%%'
                       ORDER BY id""", (region,))
    else:
        cur.execute("""SELECT id, name, source_url, website FROM companies 
                       WHERE phone IS NULL AND source_url IS NOT NULL AND source_url LIKE '%%2gis%%'
                       ORDER BY id""")
    
    companies = cur.fetchall()
    log.info(f"Found {len(companies)} companies without phone with 2GIS URLs" + (f" in {region}" if region else ""))
    
    updated = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox'
        ])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 720}
        )
        page = ctx.new_page()
        
        for i, (cid, name, source_url, existing_website) in enumerate(companies):
            try:
                phone, email, website = scrape_2gis_page(page, source_url)
                
                updates = []
                params = []
                if phone:
                    updates.append("phone = %s")
                    params.append(phone)
                if email:
                    updates.append("email = COALESCE(email, %s)")
                    params.append(email)
                if website and not existing_website:
                    updates.append("website = %s")
                    params.append(website)
                
                if updates:
                    params.append(cid)
                    sql = f"UPDATE companies SET {', '.join(updates)} WHERE id = %s"
                    cur.execute(sql, params)
                    conn.commit()
                    updated += 1
                    log.info(f"  [{i+1}/{len(companies)}] {name}: phone={phone}, email={email}")
                else:
                    log.info(f"  [{i+1}/{len(companies)}] {name}: no contacts found")
                    
            except Exception as e:
                log.error(f"  [{i+1}/{len(companies)}] Error {name}: {e}")
            
            time.sleep(random.uniform(3, 7))
            
            if (i+1) % 50 == 0:
                log.info(f"=== Progress: {i+1}/{len(companies)}, updated: {updated} ===")
        
        browser.close()
    
    log.info(f"=== DONE: {updated} companies updated out of {len(companies)} ===")
    conn.close()

if __name__ == '__main__':
    main()
