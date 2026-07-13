import os
"""
Enrich companies with website data via Google Search (Serper.dev API).
2500 free queries — prioritizes highest-rated companies first.
Run: nohup python3 /opt/mcp-market/scripts/enrich_serper.py > /opt/mcp-market/enrich.log 2>&1 &
"""
import time
import json
import sys
import re
import psycopg2
import psycopg2.extras
import requests

DB = "postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@127.0.0.1:5432/mcpmarket"
SERPER_KEY = os.environ.get("SERPER_API_KEY", "")

# Domains to skip (not company websites)
SKIP_DOMAINS = {
    "2gis.ru", "yandex.ru", "google.com", "google.ru",
    "vk.com", "ok.ru", "facebook.com", "instagram.com",
    "youtube.com", "t.me", "telegram.me", "wa.me",
    "avito.ru", "cian.ru", "domclick.ru", "yandex.com",
    "zoon.ru", "flamp.ru", "yell.ru", "irecommend.ru",
    "otzovik.com", "maps.google.com", "maps.yandex.ru",
    "ru.wikipedia.org", "wikipedia.org", "wikidata.org",
    "hh.ru", "superjob.ru", "rabota.ru", "trudvsem.ru",
    "yandex.net", "gismeteo.ru", "drom.ru", "auto.ru",
    "profi.ru", "youla.ru", "jcat.ru", "cataloxy.ru",
    "sravni.ru", "banki.ru", "list-org.com", "rusprofile.ru",
    "google.com.ua", "twitter.com", "x.com",
}


def get_db():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    return conn


def search_google(company_name, city):
    """Search Google for company website via Serper API."""
    query = f'"{company_name}" {city} официальный сайт'
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": query, "gl": "ru", "hl": "ru", "num": 5},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        else:
            return None
    except Exception as e:
        return None


def extract_website(results, company_name):
    """Extract most likely company website from search results."""
    if not results:
        return None

    organic = results.get("organic", [])
    if not organic:
        return None

    for item in organic:
        link = item.get("link", "")
        if not link:
            continue

        # Extract domain
        match = re.match(r'https?://(?:www\.)?([^/]+)', link)
        if not match:
            continue
        domain = match.group(1).lower()

        # Skip aggregators and social networks
        skip = False
        for sd in SKIP_DOMAINS:
            if domain == sd or domain.endswith("." + sd):
                skip = True
                break
        if skip:
            continue

        # Return the full domain URL
        return f"https://{domain}"

    return None


def main():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get companies without website, ordered by rating (best first)
    cur.execute("""
        SELECT id, name, city
        FROM companies
        WHERE (website IS NULL OR website = '')
        ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
        LIMIT 2400
    """)
    companies = cur.fetchall()

    print(f"Companies to enrich: {len(companies)}")
    print(f"Serper API key: {SERPER_KEY[:8]}...")
    print(f"Starting...\n")

    updated = 0
    skipped = 0
    errors = 0
    no_result = 0

    for i, company in enumerate(companies):
        cid = company["id"]
        name = company["name"]
        city = company["city"] or ""

        sys.stdout.write(f"\r[{i+1}/{len(companies)}] {name[:45]}...")
        sys.stdout.flush()

        results = search_google(name, city)
        if results is None:
            errors += 1
            time.sleep(1)
            continue

        website = extract_website(results, name)

        if website:
            cur.execute(
                "UPDATE companies SET website = %s, updated_at = NOW() WHERE id = %s",
                (website, cid),
            )
            updated += 1
        else:
            no_result += 1

        # Rate limit: ~2 requests per second
        time.sleep(0.5)

        # Progress every 100
        if (i + 1) % 100 == 0:
            print(f"\n  [{i+1}/{len(companies)}] websites: {updated} | no_result: {no_result} | errors: {errors}")

    print(f"\n\n{'='*60}")
    print(f"DONE!")
    print(f"  Processed: {len(companies)}")
    print(f"  Websites found: {updated}")
    print(f"  No website found: {no_result}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
