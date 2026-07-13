#!/usr/bin/env python3
"""
Enrich company ratings from Google Places via Serper.dev API.
Searches each company by name+city, matches results, updates rating & reviews_count.
"""

import os
import sys
import time
import json
import re
import requests
import psycopg2
from difflib import SequenceMatcher

# Config
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
SERPER_PLACES_URL = "https://google.serper.dev/places"

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "mcpmarket")
DB_USER = os.getenv("DB_USER", "mcpuser")
DB_PASS = os.getenv("DB_PASS", "mcppass")

# If running outside docker, connect via localhost mapped port
# If inside docker network, use container name
SLEEP_BETWEEN = 1.5  # seconds between API calls
SIMILARITY_THRESHOLD = 0.35  # minimum name similarity to accept match


def normalize_name(name):
    """Normalize company name for comparison."""
    if not name:
        return ""
    # Remove common suffixes and legal forms
    name = name.lower().strip()
    # Remove quotes and extra punctuation
    name = re.sub(r'[«»"\'\.,:;!\?\-\(\)]', ' ', name)
    # Remove common words that don't help matching
    stopwords = ['ооо', 'ип', 'зао', 'оао', 'пао', 'гк', 'ск', 'строительная', 'компания',
                 'группа', 'компаний', 'производственная', 'торговая', 'дом', 'строй',
                 'the', 'llc', 'inc', 'ltd']
    words = name.split()
    words = [w for w in words if w not in stopwords and len(w) > 1]
    return ' '.join(words)


def similarity(a, b):
    """Calculate similarity ratio between two strings."""
    a_norm = normalize_name(a)
    b_norm = normalize_name(b)
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def search_places(company_name, city):
    """Search Google Places via Serper API."""
    query = f"{company_name} {city}"
    payload = {
        "q": query,
        "gl": "ru",
        "hl": "ru",
        "num": 5
    }
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(SERPER_PLACES_URL, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("places", [])
    except Exception as e:
        print(f"  API error: {e}")
        return []


def find_best_match(company_name, city, places):
    """Find the best matching place for a company."""
    if not places:
        return None

    best_match = None
    best_score = 0

    for place in places:
        title = place.get("title", "")
        place_rating = place.get("rating")
        place_reviews = place.get("ratingCount")

        # Skip places without rating
        if not place_rating:
            continue

        score = similarity(company_name, title)

        # Bonus if city appears in address
        address = place.get("address", "").lower()
        if city.lower() in address:
            score += 0.1

        # Bonus if website matches
        place_website = place.get("website", "")
        if place_website:
            score += 0.05

        if score > best_score:
            best_score = score
            best_match = {
                "title": title,
                "rating": place_rating,
                "reviews_count": place_reviews or 0,
                "score": score,
                "address": place.get("address", ""),
                "website": place_website
            }

    if best_match and best_match["score"] >= SIMILARITY_THRESHOLD:
        return best_match
    return None


def main():
    # Determine region filter from args
    region_filter = None
    if len(sys.argv) > 1:
        region_filter = sys.argv[1]
        print(f"Region filter: {region_filter}")

    # Connect to DB
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        conn.autocommit = True
        cur = conn.cursor()
        print("Connected to database")
    except Exception as e:
        print(f"DB connection error: {e}")
        sys.exit(1)

    # Get companies without ratings
    query = """
        SELECT id, name, city, region, website
        FROM companies
        WHERE (rating IS NULL OR rating = 0)
    """
    params = []
    if region_filter:
        query += " AND (region ILIKE %s OR city ILIKE %s)"
        params = [f"%{region_filter}%", f"%{region_filter}%"]

    query += " ORDER BY name"
    cur.execute(query, params)
    companies = cur.fetchall()
    total = len(companies)
    print(f"Found {total} companies without ratings")

    if total == 0:
        print("Nothing to do!")
        cur.close()
        conn.close()
        return

    updated = 0
    no_match = 0
    errors = 0
    skipped = 0

    for i, (cid, name, city, region, website) in enumerate(companies):
        city_search = city or ""
        if not city_search and region:
            city_search = region

        print(f"[{i+1}/{total}] {name} ({city_search})...", end=" ", flush=True)

        if not name or len(name.strip()) < 2:
            print("SKIP (no name)")
            skipped += 1
            continue

        try:
            places = search_places(name, city_search)
            match = find_best_match(name, city_search, places)

            if match:
                rating = round(match["rating"], 1)
                # Clamp rating to valid range
                if rating > 5.0:
                    rating = 5.0
                if rating < 1.0:
                    rating = 1.0
                reviews = int(match["reviews_count"])

                cur.execute("""
                    UPDATE companies
                    SET rating = %s, reviews_count = %s, updated_at = NOW()
                    WHERE id = %s
                """, (rating, reviews, cid))

                print(f"OK rating={rating} reviews={reviews} (match: {match['title']}, score={match['score']:.2f})")
                updated += 1
            else:
                print(f"NO MATCH (found {len(places)} places)")
                no_match += 1

        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

        # Rate limit
        time.sleep(SLEEP_BETWEEN)

        # Progress every 50
        if (i + 1) % 50 == 0:
            print(f"\n--- Progress: {i+1}/{total} | updated: {updated} | no_match: {no_match} | errors: {errors} ---\n")

    print(f"\n{'='*60}")
    print(f"DONE!")
    print(f"  Total processed: {total}")
    print(f"  Updated with ratings: {updated}")
    print(f"  No match found: {no_match}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
