"""
FULL company enrichment — one pass, maximum data extraction.
Parses each company website and extracts: phone, email, description,
social links, prices, INN/OGRN, founding year, site status.

Run: nohup python3 /opt/mcp-market/scripts/enrich_full.py > /opt/mcp-market/enrich_full.log 2>&1 &
"""
import re
import sys
import time
import json
import psycopg2
import psycopg2.extras
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB = "postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@127.0.0.1:5432/mcpmarket"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}


def get_db():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    return conn


# ─── EXTRACTORS ─────────────────────────────────────────────────────

def extract_phones(html_text):
    """Extract Russian phone numbers."""
    patterns = [
        r'[\+]?[78][\s\-\(]?\d{3}[\s\-\)]?\s?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
        r'8[\s\-]?800[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
    ]
    phones = set()
    for p in patterns:
        for m in re.findall(p, html_text):
            cleaned = re.sub(r'[^\d+]', '', m)
            if len(cleaned) >= 11:
                # Normalize
                if cleaned.startswith('8') and len(cleaned) == 11:
                    cleaned = '+7' + cleaned[1:]
                elif cleaned.startswith('7') and len(cleaned) == 11:
                    cleaned = '+7' + cleaned[1:]
                elif cleaned.startswith('+7'):
                    pass
                else:
                    continue
                # Format nicely
                d = cleaned.replace('+7', '')
                formatted = f"+7 ({d[:3]}) {d[3:6]}-{d[6:8]}-{d[8:10]}"
                phones.add(formatted)
    return list(phones)[:3]  # Max 3 phones


def extract_emails(html_text):
    """Extract email addresses, skip junk."""
    junk_domains = {
        'example.com', 'test.com', 'email.com', 'domain.com',
        'sentry.io', 'w3.org', 'schema.org', 'googleapis.com',
        'google.com', 'googletagmanager.com', 'facebook.com',
        'yandex.ru', 'yandex.net', 'gstatic.com', 'cloudflare.com',
        'jquery.com', 'jsdelivr.net', 'wp.com', 'wordpress.org',
        'gravatar.com', 'bootstrapcdn.com', 'fontawesome.com',
    }
    emails = set()
    for m in re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html_text):
        domain = m.split('@')[1].lower()
        if domain not in junk_domains and not domain.endswith('.js') and not domain.endswith('.css'):
            emails.add(m.lower())
    return list(emails)[:2]


def extract_description(soup, company_name):
    """Extract company description."""
    # 1. Meta description
    meta = soup.find("meta", attrs={"name": "description"})
    meta_desc = ""
    if meta and meta.get("content"):
        meta_desc = re.sub(r'\s+', ' ', meta["content"]).strip()

    # 2. OG description
    og = soup.find("meta", attrs={"property": "og:description"})
    og_desc = ""
    if og and og.get("content"):
        og_desc = re.sub(r'\s+', ' ', og["content"]).strip()

    # 3. Text from about sections
    about_text = ""
    for selector in ["[class*='about']", "[class*='description']", "[class*='intro']",
                     "[class*='company']", "[class*='welcome']", "[id*='about']",
                     "article", "main .content", "main"]:
        for el in soup.select(selector):
            text = re.sub(r'\s+', ' ', el.get_text()).strip()
            if 50 < len(text) < 1000:
                # Check for useful keywords
                lower = text.lower()
                if any(kw in lower for kw in ['строи', 'дом', 'компания', 'услуг', 'проект',
                                                'ремонт', 'монтаж', 'недвижим', 'фундамент']):
                    about_text = text
                    break
        if about_text:
            break

    # Pick best description
    candidates = [(meta_desc, 2), (og_desc, 1), (about_text, 3)]
    candidates.sort(key=lambda x: (-x[1] if 30 < len(x[0]) < 800 else 0))

    for text, _ in candidates:
        if 30 < len(text) < 800:
            # Clean up
            text = text.strip()
            if text.lower().startswith(company_name.lower()):
                text = text[len(company_name):].strip(' -–—:.,')
            return text[:800]

    return None


def extract_socials(soup):
    """Extract social media links."""
    socials = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if "vk.com/" in href and "share" not in href:
            socials["vk"] = a["href"]
        elif "t.me/" in href or "telegram" in href:
            socials["telegram"] = a["href"]
        elif "wa.me/" in href or "whatsapp" in href:
            socials["whatsapp"] = a["href"]
        elif "instagram.com/" in href:
            socials["instagram"] = a["href"]
        elif "youtube.com/" in href or "youtu.be/" in href:
            socials["youtube"] = a["href"]
        elif "ok.ru/" in href:
            socials["ok"] = a["href"]
        elif "zen.yandex" in href or "dzen.ru" in href:
            socials["dzen"] = a["href"]
    return socials


def extract_prices(html_text):
    """Extract price indicators from page text."""
    prices = []

    # "от X руб" / "от X ₽"
    for m in re.finditer(r'от\s+([\d\s,.]+)\s*(руб|₽|рублей|р\.)', html_text, re.IGNORECASE):
        try:
            val = float(re.sub(r'[\s,.]', '', m.group(1).strip()))
            if 10000 < val < 500000000:
                prices.append(val)
        except:
            pass

    # "X руб/м²" / "X ₽/м²"
    price_per_sqm = None
    for m in re.finditer(r'([\d\s,.]+)\s*(руб|₽)\s*/\s*м[²2]', html_text, re.IGNORECASE):
        try:
            val = float(re.sub(r'[\s,.]', '', m.group(1).strip()))
            if 5000 < val < 200000:
                price_per_sqm = int(val)
                break
        except:
            pass

    # "от X тыс" / "от X млн"
    for m in re.finditer(r'от\s+([\d,.]+)\s*(тыс|млн)', html_text, re.IGNORECASE):
        try:
            val = float(m.group(1).replace(',', '.'))
            mult = 1000 if 'тыс' in m.group(2).lower() else 1000000
            total = val * mult
            if 100000 < total < 500000000:
                prices.append(total)
        except:
            pass

    min_price = int(min(prices)) if prices else None
    max_price = int(max(prices)) if len(prices) > 1 else None

    return min_price, max_price, price_per_sqm


def extract_inn_ogrn(html_text):
    """Extract INN or OGRN."""
    inn = None
    ogrn = None

    # ИНН: 10 or 12 digits
    m = re.search(r'ИНН[:\s]*(\d{10,12})', html_text, re.IGNORECASE)
    if m:
        inn = m.group(1)

    # ОГРН: 13 or 15 digits
    m = re.search(r'ОГРН[:\s]*(\d{13,15})', html_text, re.IGNORECASE)
    if m:
        ogrn = m.group(1)

    return inn, ogrn


def extract_founding_year(html_text):
    """Extract founding year."""
    patterns = [
        r'(?:с|с\s+|основан[аы]?\s+в\s+|работаем\s+с\s+|на\s+рынке\s+с\s+)(\d{4})\s*(?:года|г\.?|г\b)',
        r'(\d{4})\s*(?:года?\s+на\s+рынке|года?\s+опыт)',
        r'(?:более|свыше|уже)\s+(\d{1,2})\s+лет',
    ]
    for p in patterns:
        m = re.search(p, html_text, re.IGNORECASE)
        if m:
            val = m.group(1)
            if len(val) == 4:
                year = int(val)
                if 1990 <= year <= 2026:
                    return year
            elif len(val) <= 2:
                years = int(val)
                if 2 <= years <= 50:
                    return 2026 - years
    return None


# ─── MAIN LOGIC ─────────────────────────────────────────────────────

def fetch_page(url):
    """Fetch webpage."""
    try:
        if not url.startswith("http"):
            url = "https://" + url
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True, verify=False)
        if r.status_code == 200 and len(r.text) > 200:
            return r.text, r.status_code
        return None, r.status_code
    except requests.exceptions.Timeout:
        return None, 0
    except Exception:
        return None, -1


def enrich_company(html, company_name):
    """Extract all data from HTML page."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts, styles
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    text = soup.get_text()

    result = {}

    # Phones
    phones = extract_phones(html)  # Use raw HTML for phones (might be in href="tel:")
    if phones:
        result["phone"] = phones[0]  # Primary phone

    # Emails
    emails = extract_emails(html)
    if emails:
        result["email"] = emails[0]

    # Description
    desc = extract_description(soup, company_name)
    if desc and len(desc) > 30:
        result["description"] = desc

    # Socials
    socials = extract_socials(soup)
    if socials:
        result["socials"] = socials

    # Prices
    min_price, max_price, price_sqm = extract_prices(text)
    if min_price:
        result["min_project_price"] = min_price
    if max_price:
        result["max_project_price"] = max_price
    if price_sqm:
        result["price_per_sqm_min"] = price_sqm

    # INN/OGRN
    inn, ogrn = extract_inn_ogrn(text)
    if inn:
        result["inn"] = inn
    if ogrn:
        result["ogrn"] = ogrn

    # Founding year
    year = extract_founding_year(text)
    if year:
        result["founded_year"] = year

    return result


def main():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all companies with website
    cur.execute("""
        SELECT id, name, website, phone, email, description
        FROM companies
        WHERE website IS NOT NULL AND website != ''
        ORDER BY
            (CASE WHEN phone IS NULL OR phone = '' THEN 1 ELSE 0 END +
             CASE WHEN description IS NULL OR LENGTH(description) < 30 THEN 1 ELSE 0 END +
             CASE WHEN email IS NULL OR email = '' THEN 1 ELSE 0 END) DESC
    """)
    companies = cur.fetchall()

    print(f"Companies with websites: {len(companies)}")
    print("Extracting: phone, email, description, socials, prices, INN/OGRN, founding year")
    print(f"Starting...\n")

    stats = {
        "processed": 0, "phones": 0, "emails": 0, "descriptions": 0,
        "prices": 0, "socials": 0, "inn_ogrn": 0, "years": 0,
        "site_dead": 0, "errors": 0,
    }

    for i, company in enumerate(companies):
        cid = company["id"]
        name = company["name"]
        website = company["website"]

        sys.stdout.write(f"\r[{i+1}/{len(companies)}] {name[:45]}...")
        sys.stdout.flush()

        html, status = fetch_page(website)

        if not html:
            if status == 0:
                stats["site_dead"] += 1
            else:
                stats["errors"] += 1
            time.sleep(0.3)
            continue

        data = enrich_company(html, name)
        stats["processed"] += 1

        # Build UPDATE query — only update fields that are currently empty
        updates = []
        params = []

        # Phone: only if not already set
        if data.get("phone") and (not company.get("phone") or company["phone"] == ''):
            updates.append("phone = %s")
            params.append(data["phone"])
            stats["phones"] += 1

        # Email: only if not already set
        if data.get("email") and (not company.get("email") or company["email"] == ''):
            updates.append("email = %s")
            params.append(data["email"])
            stats["emails"] += 1

        # Description: only if not already set or too short
        if data.get("description") and (not company.get("description") or len(company.get("description", '')) < 30):
            updates.append("description = %s")
            params.append(data["description"])
            stats["descriptions"] += 1

        # Prices: only if not already set
        if data.get("min_project_price"):
            updates.append("min_project_price = COALESCE(min_project_price, %s)")
            params.append(data["min_project_price"])
            stats["prices"] += 1
        if data.get("max_project_price"):
            updates.append("max_project_price = COALESCE(max_project_price, %s)")
            params.append(data["max_project_price"])
        if data.get("price_per_sqm_min"):
            updates.append("price_per_sqm_min = COALESCE(price_per_sqm_min, %s)")
            params.append(data["price_per_sqm_min"])

        if updates:
            updates.append("updated_at = NOW()")
            params.append(cid)
            sql = f"UPDATE companies SET {', '.join(updates)} WHERE id = %s"
            cur.execute(sql, params)

        # Rate limit
        time.sleep(0.5)

        # Progress
        if (i + 1) % 100 == 0:
            print(f"\n  [{i+1}/{len(companies)}] phones:{stats['phones']} emails:{stats['emails']} "
                  f"desc:{stats['descriptions']} prices:{stats['prices']} dead:{stats['site_dead']}")

    # Final stats
    print(f"\n\n{'='*60}")
    print(f"FULL ENRICHMENT COMPLETE")
    print(f"  Companies processed: {stats['processed']}")
    print(f"  Phones extracted: {stats['phones']}")
    print(f"  Emails extracted: {stats['emails']}")
    print(f"  Descriptions extracted: {stats['descriptions']}")
    print(f"  Prices found: {stats['prices']}")
    print(f"  Dead websites: {stats['site_dead']}")
    print(f"  Errors: {stats['errors']}")
    print(f"{'='*60}")

    # Final DB stats
    cur.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE phone IS NOT NULL AND phone != '') as phones,
            COUNT(*) FILTER (WHERE email IS NOT NULL AND email != '') as emails,
            COUNT(*) FILTER (WHERE description IS NOT NULL AND LENGTH(description) > 30) as descriptions,
            COUNT(*) FILTER (WHERE website IS NOT NULL AND website != '') as websites,
            COUNT(*) FILTER (WHERE min_project_price IS NOT NULL) as with_prices
        FROM companies
    """)
    db_stats = cur.fetchone()
    print(f"\nDATABASE STATUS:")
    print(f"  Total companies: {db_stats['total']}")
    print(f"  With phone: {db_stats['phones']}")
    print(f"  With email: {db_stats['emails']}")
    print(f"  With description: {db_stats['descriptions']}")
    print(f"  With website: {db_stats['websites']}")
    print(f"  With prices: {db_stats['with_prices']}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
