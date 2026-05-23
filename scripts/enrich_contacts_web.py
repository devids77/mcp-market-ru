#!/usr/bin/env python3
"""Enrich contacts (phone, email) from company websites."""
import re
import time
import logging
import psycopg2
import urllib.request
import urllib.error
from html.parser import HTMLParser
import ssl

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_URL = 'postgresql://mcpuser:McpMarket2026Secure@localhost:5432/mcpmarket'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip = True
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = False
    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)

def fetch_page(url, timeout=15):
    try:
        if not url.startswith('http'):
            url = 'https://' + url
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read(500000)
            for enc in ['utf-8', 'cp1251', 'latin-1']:
                try:
                    return data.decode(enc)
                except:
                    continue
            return data.decode('utf-8', errors='ignore')
    except Exception as e:
        return None

def extract_phones(html):
    """Extract phones from HTML including tel: links and text patterns."""
    phones = set()
    # tel: links
    for m in re.finditer(r'href=["\']tel:([^"\']+)', html, re.I):
        raw = re.sub(r'[^\d+]', '', m.group(1))
        if len(raw) >= 10:
            phones.add(raw)
    # Text patterns: +7/8 (XXX) XXX-XX-XX variants
    ext = TextExtractor()
    try:
        ext.feed(html)
    except:
        pass
    text = ' '.join(ext.text)
    patterns = [
        r'(?:\+7|8)[\s\-]*\(?(\d{3})\)?[\s\-]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})',
        r'(?:\+7|8)[\s\-]*(\d{3})[\s\-]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            digits = ''.join(m.groups())
            if len(digits) == 10:
                phones.add('+7' + digits)
    # Also check raw HTML for phones in attributes
    for m in re.finditer(r'(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}', html):
        raw = re.sub(r'[^\d+]', '', m.group())
        if raw.startswith('8') and len(raw) == 11:
            raw = '+7' + raw[1:]
        if len(raw) >= 11:
            phones.add(raw)
    return list(phones)[:3]

def extract_emails(html):
    """Extract emails from HTML including mailto: links."""
    emails = set()
    # mailto: links
    for m in re.finditer(r'href=["\']mailto:([^"\'?]+)', html, re.I):
        email = m.group(1).strip().lower()
        if re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$', email):
            emails.add(email)
    # Text pattern
    ext = TextExtractor()
    try:
        ext.feed(html)
    except:
        pass
    text = ' '.join(ext.text)
    for m in re.finditer(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text):
        email = m.group().lower()
        # Skip image/file extensions
        if not email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js')):
            emails.add(email)
    return list(emails)[:3]

def find_contact_pages(html, base_url):
    """Find links to contact pages."""
    pages = []
    keywords = ['контакт', 'contact', 'о нас', 'about', 'связ', 'обратн', 'реквизит']
    for m in re.finditer(r'href=["\']([^"\'#]+)["\']', html, re.I):
        href = m.group(1)
        href_lower = href.lower()
        if any(k in href_lower for k in keywords):
            if href.startswith('/'):
                # Make absolute URL
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            elif not href.startswith('http'):
                href = base_url.rstrip('/') + '/' + href
            if href not in pages:
                pages.append(href)
    return pages[:3]

def enrich_company(cur, company):
    cid, slug, website, phone, email = company
    if not website:
        return False
    
    url = website if website.startswith('http') else 'https://' + website
    base_url = url
    
    all_phones = []
    all_emails = []
    
    # Fetch main page
    html = fetch_page(url)
    if not html:
        return False
    
    all_phones.extend(extract_phones(html))
    all_emails.extend(extract_emails(html))
    
    # If not enough, check contact pages
    if not all_phones or not all_emails:
        contact_pages = find_contact_pages(html, base_url)
        for cp_url in contact_pages:
            time.sleep(0.5)
            cp_html = fetch_page(cp_url)
            if cp_html:
                if not all_phones:
                    all_phones.extend(extract_phones(cp_html))
                if not all_emails:
                    all_emails.extend(extract_emails(cp_html))
                if all_phones and all_emails:
                    break
    
    updated = False
    updates = []
    params = []
    
    if not phone and all_phones:
        updates.append("phone = %s")
        params.append(all_phones[0])
        updated = True
    
    if not email and all_emails:
        updates.append("email = %s")
        params.append(all_emails[0])
        updated = True
    
    if updates:
        params.append(cid)
        cur.execute(f"UPDATE companies SET {', '.join(updates)} WHERE id = %s", params)
        return True
    return False

def main():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    
    # Get companies with website but missing phone OR email
    cur.execute("""
        SELECT id, slug, website, phone, email FROM companies 
        WHERE website IS NOT NULL AND (phone IS NULL OR email IS NULL)
        ORDER BY id
    """)
    companies = cur.fetchall()
    total = len(companies)
    log.info(f"Found {total} companies to enrich contacts from websites")
    
    found_phone = 0
    found_email = 0
    
    for i, company in enumerate(companies, 1):
        try:
            cid, slug, website, phone, email = company
            result = enrich_company(cur, company)
            
            # Re-check what was updated
            cur.execute("SELECT phone, email FROM companies WHERE id = %s", (cid,))
            new_phone, new_email = cur.fetchone()
            
            ph_status = "PHONE" if (not phone and new_phone) else ""
            em_status = "EMAIL" if (not email and new_email) else ""
            found_str = f"{ph_status} {em_status}".strip()
            
            if not phone and new_phone:
                found_phone += 1
            if not email and new_email:
                found_email += 1
            
            if found_str:
                log.info(f"[{i}/{total}] {slug}: {found_str} FOUND")
            else:
                if i % 50 == 0:
                    log.info(f"[{i}/{total}] progress... phones={found_phone}, emails={found_email}")
            
            time.sleep(0.3)
        except Exception as e:
            log.error(f"[{i}/{total}] {slug}: {e}")
    
    log.info(f"=== DONE: {found_phone} phones, {found_email} emails from {total} companies ===")
    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
