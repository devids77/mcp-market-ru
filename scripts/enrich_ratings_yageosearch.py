#!/usr/bin/env python3
"""Enrich company ratings via Yandex Geosearch API (Organizations).
Free tier: 500 requests/day. We use ~1-2 requests per company.
API docs: https://yandex.ru/dev/geosearch/doc/ru/request
"""
import os, sys, re, time, logging, json
import httpx
import psycopg2
from difflib import SequenceMatcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# Config
YANDEX_API_KEY = os.getenv("YANDEX_GEOSEARCH_KEY", "0c821f22-f1d9-4fb6-b0ea-5ed523b87b19")
GEOSEARCH_URL = "https://search-maps.yandex.ru/v1/"
DB_CONN = f"postgresql://{os.getenv('DB_USER','mcpuser')}:{os.getenv('DB_PASS','CHANGE_ME_DB_PASSWORD_FROM_ENV')}@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','mcpmarket')}"

# Rate limiting: stay well under 500/day
REQUEST_DELAY = 2  # seconds between API calls
SIMILARITY_THRESHOLD = 0.35

def normalize(name):
    if not name: return ""
    name = name.lower().strip()
    name = re.sub(r'["\'\.,;:!\?\(\)\-]', ' ', name)
    stops = ['ооо','зао','ип','ск','гк','строительная','компания',
             'производственная','торговая','дом','строй','группа',
             'the','llc','inc','ltd','фирма']
    words = [w for w in name.split() if w not in stops and len(w) > 1]
    return ' '.join(words)

def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def search_organizations(query, lang="ru_RU", results=5):
    """Search Yandex Geosearch API for organizations."""
    params = {
        "apikey": YANDEX_API_KEY,
        "text": query,
        "type": "biz",
        "lang": lang,
        "results": results,
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(GEOSEARCH_URL, params=params)
            if resp.status_code == 403:
                log.error("API key rejected (403). Check key validity.")
                return None
            if resp.status_code == 429:
                log.warning("Rate limit hit (429). Waiting 60s...")
                time.sleep(60)
                return []
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            results_list = []
            for f in features:
                props = f.get("properties", {})
                meta = props.get("CompanyMetaData", {})
                name = meta.get("name", props.get("name", ""))
                address = meta.get("address", "")
                url = meta.get("url", "")
                phones = [p.get("formatted", "") for p in meta.get("Phones", [])]
                # Extract rating
                rating_info = {}
                for ref in meta.get("References", []):
                    if ref.get("scope") == "nyak":  # Yandex ratings
                        rating_info = {
                            "rating": ref.get("rating", 0),
                            "reviews": ref.get("count", 0),
                        }
                results_list.append({
                    "name": name,
                    "address": address,
                    "url": url,
                    "phones": phones,
                    "rating": rating_info.get("rating", 0),
                    "reviews": rating_info.get("reviews", 0),
                    "categories": [c.get("name", "") for c in meta.get("Categories", [])],
                })
            return results_list
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error: {e.response.status_code} {e.response.text[:200]}")
        return None
    except Exception as e:
        log.error(f"Request error: {e}")
        return None

def find_best_match(company_name, city, results):
    """Find the best matching organization from search results."""
    if not results:
        return None
    best_score = 0
    best_match = None
    for r in results:
        # Name similarity
        score = similarity(company_name, r["name"])
        # Bonus if city appears in address
        if city and city.lower() in r.get("address", "").lower():
            score += 0.1
        # Bonus if has rating
        if r["rating"] > 0:
            score += 0.05
        if score > best_score:
            best_score = score
            best_match = r
    if best_score >= SIMILARITY_THRESHOLD and best_match:
        best_match["match_score"] = best_score
        return best_match
    return None

def main():
    region_filter = sys.argv[1] if len(sys.argv) > 1 else None

    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    query = """SELECT id, name, city, region, website
               FROM companies
               WHERE (rating IS NULL OR rating = 0)"""
    params = []
    if region_filter:
        query += " AND (region ILIKE %s OR city ILIKE %s)"
        params = [f"%{region_filter}%", f"%{region_filter}%"]
    query += " ORDER BY name"

    cur.execute(query, params)
    companies = cur.fetchall()
    total = len(companies)
    log.info(f"Found {total} companies without ratings" +
             (f" in '{region_filter}'" if region_filter else ""))
    log.info(f"API key: {YANDEX_API_KEY[:8]}...{YANDEX_API_KEY[-4:]}")
    log.info(f"Rate: {REQUEST_DELAY}s between requests, ~{total} API calls needed")

    updated = 0
    no_match = 0
    no_rating = 0
    errors = 0
    api_calls = 0

    for i, (cid, name, city, region, website) in enumerate(companies):
        if not name or len(name.strip()) < 2:
            log.info(f"[{i+1}/{total}] SKIP (no name)")
            continue

        search_city = city or region or "Санкт-Петербург"
        search_query = f"{name} {search_city}"
        log.info(f"[{i+1}/{total}] {name} ({search_city})")

        # Rate limiting
        time.sleep(REQUEST_DELAY)

        try:
            results = search_organizations(search_query)
            api_calls += 1

            if results is None:
                errors += 1
                log.error("  API error, stopping to preserve quota")
                break

            match = find_best_match(name, search_city, results)

            if match:
                rating = match["rating"]
                reviews = match["reviews"]
                if rating > 0:
                    rating = min(5.0, max(1.0, round(float(rating), 1)))
                    reviews = int(reviews) if reviews else 0
                    cur.execute(
                        "UPDATE companies SET rating=%s, reviews_count=%s WHERE id=%s",
                        (rating, reviews, cid))
                    conn.commit()
                    updated += 1
                    log.info(f"  MATCH: '{match['name']}' (score={match['match_score']:.2f})")
                    log.info(f"  UPDATED: rating={rating}, reviews={reviews}")
                else:
                    no_rating += 1
                    log.info(f"  MATCH: '{match['name']}' but no rating on Yandex")
            else:
                no_match += 1
                if results:
                    log.info(f"  No good match. Best candidate: '{results[0]['name']}' "
                            f"(sim={similarity(name, results[0]['name']):.2f})")
                else:
                    log.info(f"  No results found")

        except Exception as e:
            errors += 1
            log.error(f"  ERROR: {e}")
            conn.rollback()

    cur.close()
    conn.close()

    log.info("=" * 60)
    log.info(f"RESULTS:")
    log.info(f"  Total processed: {total}")
    log.info(f"  API calls made: {api_calls}")
    log.info(f"  Updated with ratings: {updated}")
    log.info(f"  Matched but no Yandex rating: {no_rating}")
    log.info(f"  No match found: {no_match}")
    log.info(f"  Errors: {errors}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
