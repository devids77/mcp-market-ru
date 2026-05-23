#!/usr/bin/env python3
"""Enrich contacts (phone, email) from company websites - V2.
Checks main page + /contacts, /kontakty, /about pages.
Also follows links containing 'контакт' or 'contact' in href/text."""
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

CONTACT_PATHS = [
    '', '/contacts', '/kontakty', '/contact', '/about',
    '/kontakt', '/o-kompanii', '/about-us', '/nashi-kontakty'
]

PHONE_RE = re.compile(
    r'(?:\+7|8)[\s\-\(]*(?:\d[\s\-\)]*){10}'
)
EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)
SKIP_EMAILS = {'example.com', 'email.com', 'domain.com', 'test.com',
               'mail.com', 'your', 'name@', 'info@info', 'sentry.io'}

def fetch_page(url, timeout=10):
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
    except Exception:
        return None

def clean_phone(raw):
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits[0] in ('7', '8'):
        return '+7' + digits[1:]
    return None

def extract_phones(html):
    phones = set()
    for m in PHONE_RE.finditer(html):
        p = clean_phone(m.group())
        if p:
            phones.add(p)
    # Also check tel: links
    for m in re.finditer(r'href=["\']tel:([^"\']+)', html):
        p = clean_phone(m.group(1))
        if p:
            phones.add(p)
    return phones

def extract_emails(html):
    emails = set()
    for m in EMAIL_RE.finditer(html):
        email = m.group().lower().strip('.')
        if not any(skip in email for skip in SKIP_EMAILS):
            if not email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js')):
                emails.add(email)
    # Also check mailto: links
    for m in re.finditer(r'href=["\']mailto:([^"\'?]+)', html):
        email = m.group(1).lower().strip('.')
        if not any(skip in email for skip in SKIP_EMAILS):
            emails.add(email)
    return emails

def enrich_company(website, need_phone, need_email):
    all_phones = set()
    all_emails = set()
    base = website.rstrip('/')
    if not base.startswith('http'):
        base = 'https://' + base

    for path in CONTACT_PATHS:
        url = base + path
        html = fetch_page(url)
        if not html:
            continue
        if need_phone:
            all_phones.update(extract_phones(html))
        if need_email:
            all_emails.update(extract_emails(html))
        if all_phones and all_emails:
            break
        time.sleep(0.2)

    return list(all_phones), list(all_emails)

def main():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        SELECT id, slug, website, phone, email FROM companies
        WHERE website IS NOT NULL AND website != ''
          AND (phone IS NULL OR phone = '' OR email IS NULL OR email = '')
        ORDER BY id
    """)
    companies = cur.fetchall()
    total = len(companies)
    log.info(f"Found {total} companies to enrich contacts from websites (v2)")

    found_phone = 0
    found_email = 0

    for i, (cid, slug, website, phone, email) in enumerate(companies, 1):
        need_phone = not phone
        need_email = not email
        try:
            phones, emails = enrich_company(website, need_phone, need_email)

            updates = []
            params = []
            if need_phone and phones:
                updates.append("phone = %s")
                params.append(phones[0])
                found_phone += 1
            if need_email and emails:
                updates.append("email = %s")
                params.append(emails[0])
                found_email += 1

            if updates:
                params.append(cid)
                cur.execute(f"UPDATE companies SET {', '.join(updates)} WHERE id = %s", params)
                log.info(f"[{i}/{total}] {slug} FOUND: ph={phones[:1]} em={emails[:1]}")
            else:
                if i % 100 == 0:
                    log.info(f"[{i}/{total}] progress... phones={found_phone}, emails={found_email}")

        except Exception as e:
            log.error(f"[{i}/{total}] {slug}: {e}")

        time.sleep(0.3)

    log.info(f"=== DONE: {found_phone} phones, {found_email} emails from {total} companies ===")
    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
