#!/usr/bin/env python3
"""Parse reviews/testimonials from company websites.
Looks for review pages on company sites, extracts review count and average rating.
Updates companies table with website-sourced ratings."""
import os, sys, re, time, logging
import httpx
from bs4 import BeautifulSoup
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

DB_CONN = f"postgresql://{os.getenv('DB_USER','mcpuser')}:{os.getenv('DB_PASS','CHANGE_ME_DB_PASSWORD_FROM_ENV')}@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME','mcpmarket')}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

REVIEW_KEYWORDS = ['отзыв', 'review', 'testimonial', 'рейтинг', 'оценк', 'клиент', 'feedback']
REVIEW_LINK_PATTERNS = [
    re.compile(r'(?:отзыв|review|testimonial|feedback)', re.I),
]

def fetch(url, timeout=12):
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout, verify=False) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text
    except:
        return None

def find_review_pages(base_url, html):
    """Find links that likely lead to review pages."""
    soup = BeautifulSoup(html, 'lxml')
    pages = set()
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text(strip=True).lower()
        # Check link text or href for review keywords
        if any(kw in text for kw in ['отзыв', 'review', 'testimonial', 'feedback']):
            pages.add(href)
        elif any(kw in href.lower() for kw in ['otziv', 'otzyv', 'review', 'testimonial', 'feedback']):
            pages.add(href)
    # Normalize URLs
    result = []
    for href in pages:
        if href.startswith('http'):
            result.append(href)
        elif href.startswith('/'):
            result.append(base_url.rstrip('/') + href)
        elif not href.startswith('#') and not href.startswith('mailto') and not href.startswith('tel'):
            result.append(base_url.rstrip('/') + '/' + href)
    return result[:5]  # Limit to 5 review pages

def extract_reviews_from_page(html):
    """Extract review data from a page."""
    if not html:
        return 0, []
    soup = BeautifulSoup(html, 'lxml')
    text = soup.get_text(' ', strip=True)

    reviews = []
    ratings_found = []

    # Strategy 1: Look for structured review blocks (common patterns)
    review_selectors = [
        '.review', '.otzyv', '.testimonial', '.comment',
        '[class*="review"]', '[class*="otzyv"]', '[class*="testimonial"]',
        '[class*="feedback"]', '[class*="comment"]',
        '[itemtype*="Review"]',
    ]
    for sel in review_selectors:
        blocks = soup.select(sel)
        if blocks:
            for block in blocks:
                review_text = block.get_text(strip=True)
                if len(review_text) > 20:  # Minimum review length
                    reviews.append(review_text[:200])
                # Look for rating in review block
                star_el = block.select_one('[class*="star"], [class*="rating"], [class*="score"]')
                if star_el:
                    rating_match = re.search(r'(\d[.,]\d)', star_el.get_text())
                    if rating_match:
                        r = float(rating_match.group(1).replace(',', '.'))
                        if 1.0 <= r <= 5.0:
                            ratings_found.append(r)
            if reviews:
                break

    # Strategy 2: Count review-like blocks by looking at repeated similar structures
    if not reviews:
        # Look for repeated div/article/li structures with enough text
        for tag in ['article', 'div', 'li']:
            containers = soup.find_all(tag)
            # Group by class
            class_groups = {}
            for el in containers:
                cls = ' '.join(sorted(el.get('class', [])))
                if cls and len(el.get_text(strip=True)) > 30:
                    class_groups.setdefault(cls, []).append(el)
            # Find group with 3+ similar elements (likely reviews)
            for cls, elements in class_groups.items():
                if len(elements) >= 3:
                    for el in elements:
                        txt = el.get_text(strip=True)
                        if len(txt) > 30:
                            reviews.append(txt[:200])

    # Strategy 3: Extract ratings from page text
    # Common patterns: "4.8 из 5", "4.8/5", "Rating: 4.8"
    for m in re.finditer(r'(\d[.,]\d)\s*(?:из|/)\s*5', text):
        r = float(m.group(1).replace(',', '.'))
        if 1.0 <= r <= 5.0:
            ratings_found.append(r)

    # Also check structured data
    for m in re.finditer(r'"ratingValue"[:\s]*"?([\d.,]+)"?', text):
        r = float(m.group(1).replace(',', '.'))
        if 1.0 <= r <= 5.0:
            ratings_found.append(r)

    avg_rating = round(sum(ratings_found) / len(ratings_found), 1) if ratings_found else None
    return len(reviews), avg_rating

def process_company(cid, name, website, city):
    """Process a single company website for reviews."""
    if not website:
        return None, None

    # Ensure URL has scheme
    if not website.startswith('http'):
        website = 'https://' + website

    log.info(f"  Fetching {website}")
    html = fetch(website)
    if not html:
        return None, None

    total_reviews = 0
    best_rating = None

    # Check main page for reviews/ratings
    count, rating = extract_reviews_from_page(html)
    total_reviews += count
    if rating:
        best_rating = rating

    # Find and check review pages
    review_pages = find_review_pages(website, html)
    if review_pages:
        log.info(f"  Found {len(review_pages)} review page links")
    for page_url in review_pages:
        time.sleep(1)
        log.info(f"  Checking: {page_url}")
        page_html = fetch(page_url)
        if page_html:
            count, rating = extract_reviews_from_page(page_html)
            total_reviews += count
            if rating and (best_rating is None or count > 0):
                best_rating = rating

    return total_reviews, best_rating

def main():
    region_filter = sys.argv[1] if len(sys.argv) > 1 else None

    conn = psycopg2.connect(DB_CONN)
    cur = conn.cursor()

    query = """SELECT id, name, website, city, rating, reviews_count
               FROM companies
               WHERE (rating IS NULL OR rating = 0)
               AND website IS NOT NULL AND website != ''"""
    params = []
    if region_filter:
        query += " AND (region ILIKE %s OR city ILIKE %s)"
        params = [f"%{region_filter}%", f"%{region_filter}%"]
    query += " ORDER BY name"

    cur.execute(query, params)
    companies = cur.fetchall()
    total = len(companies)
    log.info(f"Found {total} companies without ratings that have websites")

    updated = 0
    found_reviews = 0

    for i, (cid, name, website, city, rating, reviews_count) in enumerate(companies):
        log.info(f"[{i+1}/{total}] {name} ({city})")
        try:
            rev_count, rev_rating = process_company(cid, name, website, city)

            if rev_count and rev_count > 0:
                found_reviews += 1
                log.info(f"  Found {rev_count} reviews" + (f", rating={rev_rating}" if rev_rating else ""))

                update_fields = []
                update_vals = []
                if rev_rating:
                    update_fields.append("rating = %s")
                    update_vals.append(rev_rating)
                if rev_count > (reviews_count or 0):
                    update_fields.append("reviews_count = %s")
                    update_vals.append(rev_count)

                if update_fields:
                    update_vals.append(cid)
                    cur.execute(f"UPDATE companies SET {', '.join(update_fields)} WHERE id = %s", update_vals)
                    conn.commit()
                    updated += 1
            elif rev_rating:
                cur.execute("UPDATE companies SET rating = %s WHERE id = %s", (rev_rating, cid))
                conn.commit()
                updated += 1
                log.info(f"  Rating from page: {rev_rating}")
            else:
                log.info(f"  No reviews/rating found")
        except Exception as e:
            log.error(f"  ERROR: {e}")
            conn.rollback()

        time.sleep(1.5)

    cur.close()
    conn.close()

    log.info("=" * 50)
    log.info(f"Companies with reviews found: {found_reviews}")
    log.info(f"Companies updated: {updated}")
    log.info(f"Total processed: {total}")
    log.info("=" * 50)

if __name__ == "__main__":
    main()
