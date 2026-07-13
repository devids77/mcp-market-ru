import os
"""
Enrich companies with website data from 2GIS profile API.
Uses source_id to fetch individual company profiles.
Run: python3 /opt/mcp-market/scripts/enrich_websites.py
"""
import time
import sys
import psycopg2
import psycopg2.extras
import requests

DB = "postgresql://mcpuser:CHANGE_ME_DB_PASSWORD_FROM_ENV@127.0.0.1:5432/mcpmarket"
KEY = os.environ.get("DGIS_API_KEY", "")


def get_db():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    return conn


def fetch_profile(source_id):
    """Fetch company profile from 2GIS by ID."""
    try:
        r = requests.get(
            "https://catalog.api.2gis.com/3.0/items/byid",
            params={
                "id": source_id,
                "key": KEY,
                "fields": "items.contact_groups,items.reviews,items.description,items.schedule",
            },
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get("result", {}).get("items", [])
            return items[0] if items else None
    except Exception as e:
        print(f"  Error fetching {source_id}: {e}")
    return None


def extract_contacts(item):
    """Extract website, phone, description from 2GIS profile."""
    website = None
    phone = None
    description = item.get("description", "")

    for group in item.get("contact_groups", []):
        for contact in group.get("contacts", []):
            ctype = contact.get("type", "")
            if ctype == "website" and not website:
                website = contact.get("url") or contact.get("text") or contact.get("value")
            elif ctype == "phone" and not phone:
                phone = contact.get("text") or contact.get("value")

    # Clean website
    if website:
        website = website.strip()
        if not website.startswith("http"):
            website = "https://" + website

    return website, phone, description


def main():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get companies without website that have source_id
    cur.execute("""
        SELECT id, name, source_id, phone, description
        FROM companies 
        WHERE source = '2gis' 
          AND source_id IS NOT NULL 
          AND source_id != ''
          AND (website IS NULL OR website = '')
        ORDER BY rating DESC NULLS LAST
    """)
    companies = cur.fetchall()

    print(f"Companies without website: {len(companies)}")
    print(f"Starting enrichment...\n")

    updated_website = 0
    updated_phone = 0
    updated_desc = 0
    errors = 0

    for i, company in enumerate(companies):
        cid = company["id"]
        name = company["name"]
        source_id = company["source_id"]

        sys.stdout.write(f"\r[{i+1}/{len(companies)}] {name[:40]}...")
        sys.stdout.flush()

        profile = fetch_profile(source_id)
        if not profile:
            errors += 1
            time.sleep(0.5)
            continue

        website, phone, description = extract_contacts(profile)

        updates = []
        params = []

        if website:
            updates.append("website = %s")
            params.append(website)
            updated_website += 1

        if phone and not company.get("phone"):
            updates.append("phone = COALESCE(NULLIF(%s, ''), phone)")
            params.append(phone)
            updated_phone += 1

        if description and not company.get("description"):
            updates.append("description = COALESCE(NULLIF(%s, ''), description)")
            params.append(description)
            updated_desc += 1

        if updates:
            updates.append("updated_at = NOW()")
            params.append(cid)
            sql = f"UPDATE companies SET {', '.join(updates)} WHERE id = %s"
            cur.execute(sql, params)

        # Rate limit: ~3 requests per second
        time.sleep(0.35)

        # Progress report every 100
        if (i + 1) % 100 == 0:
            print(f"\n  Progress: {i+1}/{len(companies)} | websites: {updated_website} | phones: {updated_phone} | desc: {updated_desc} | errors: {errors}")

    print(f"\n\n{'='*60}")
    print(f"DONE!")
    print(f"  Companies processed: {len(companies)}")
    print(f"  Websites added: {updated_website}")
    print(f"  Phones updated: {updated_phone}")
    print(f"  Descriptions added: {updated_desc}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
