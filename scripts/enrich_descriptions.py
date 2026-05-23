#!/usr/bin/env python3
"""Enrich company descriptions from their websites."""
import psycopg2
import psycopg2.extras
import urllib.request
import ssl
import re
import time
import sys

DB = "postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket"

def get_db():
    return psycopg2.connect(DB)

def fetch_page(url, timeout=10):
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read(200000)
            charset = resp.headers.get_content_charset() or 'utf-8'
            return data.decode(charset, errors='ignore')
    except Exception as e:
        return None

def extract_description(html):
    """Extract meaningful description from HTML."""
    if not html:
        return None
    
    # Try meta description first
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']{20,500})["\']', html, re.I)
    if m:
        desc = m.group(1).strip()
        if len(desc) >= 30:
            return desc
    
    # Try og:description
    m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']{20,500})["\']', html, re.I)
    if m:
        desc = m.group(1).strip()
        if len(desc) >= 30:
            return desc
    
    # Try first meaningful paragraph
    # Remove scripts and styles
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S|re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S|re.I)
    
    # Find paragraphs
    paragraphs = re.findall(r'<p[^>]*>(.{40,500}?)</p>', text, re.S|re.I)
    for p in paragraphs:
        # Clean HTML tags
        clean = re.sub(r'<[^>]+>', '', p).strip()
        clean = re.sub(r'\s+', ' ', clean)
        # Skip navigation/menu/cookie text
        if any(skip in clean.lower() for skip in ['cookie', 'javascript', 'браузер', 'copyright', '©']):
            continue
        if len(clean) >= 40:
            return clean[:500]
    
    return None

def extract_services(html):
    """Extract list of services from the page."""
    if not html:
        return []
    
    services = set()
    # Look for list items in service sections
    # Common patterns: <li> items near keywords like услуги, работы, направления
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S|re.I)
    
    # Find <li> items
    items = re.findall(r'<li[^>]*>([^<]{5,100})</li>', text, re.I)
    for item in items:
        clean = item.strip()
        if any(kw in clean.lower() for kw in ['строительств', 'ремонт', 'отделк', 'проектиров', 'фундамент', 
            'кровл', 'фасад', 'инженер', 'электр', 'сантехн', 'монтаж', 'демонтаж', 'утепл',
            'гидроизол', 'канализ', 'отопл', 'вентиляц', 'бетон', 'кладк']):
            services.add(clean[:100])
    
    return list(services)[:10]

def main():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Get companies with websites but no description
    cur.execute("""
        SELECT id, name, slug, website
        FROM companies
        WHERE website IS NOT NULL 
        AND (description IS NULL OR description = '')
        ORDER BY reviews_count DESC NULLS LAST
        LIMIT 500
    """)
    companies = cur.fetchall()
    print(f"Found {len(companies)} companies to enrich descriptions")
    
    enriched = 0
    errors = 0
    
    for i, company in enumerate(companies):
        try:
            url = company['website']
            if not url.startswith('http'):
                url = 'https://' + url
            
            html = fetch_page(url)
            if not html:
                errors += 1
                continue
            
            desc = extract_description(html)
            services = extract_services(html)
            
            if desc:
                # Also try to extract services as part of description
                full_desc = desc
                if services:
                    full_desc += " Услуги: " + ", ".join(services[:5])
                
                cur.execute("""
                    UPDATE companies SET description = %s WHERE id = %s
                """, (full_desc[:1000], company['id']))
                conn.commit()
                enriched += 1
                print(f"[{i+1}/{len(companies)}] +DESC: {company['name'][:40]} | {desc[:60]}...")
            else:
                if services:
                    svc_desc = f"Компания {company['name']}. Услуги: {', '.join(services[:5])}"
                    cur.execute("""
                        UPDATE companies SET description = %s WHERE id = %s
                    """, (svc_desc[:1000], company['id']))
                    conn.commit()
                    enriched += 1
                    print(f"[{i+1}/{len(companies)}] +SVC: {company['name'][:40]} | {svc_desc[:60]}...")
                else:
                    print(f"[{i+1}/{len(companies)}] SKIP: {company['name'][:40]}")
            
            time.sleep(0.5)
            
        except Exception as e:
            errors += 1
            print(f"[{i+1}/{len(companies)}] ERR: {company['name'][:40]} | {e}")
            continue
        
        if (i+1) % 50 == 0:
            print(f"\n--- Progress: {i+1}/{len(companies)}, enriched: {enriched}, errors: {errors} ---\n")
    
    print(f"\n=== DONE: enriched {enriched}/{len(companies)}, errors: {errors} ===")
    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
