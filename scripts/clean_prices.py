#!/usr/bin/env python3
"""Quarantine price_per_sqm values this catalogue cannot stand behind.

Every money answer the server gives — calculate_cost, project_estimator,
price_comparison, market_report tiers, budget filters — is built on
companies.price_per_sqm_min/max, and that column is not trustworthy:

  * 878 of 3231 priced rows (27%) store a max BELOW the min, so the range is
    self-contradictory and there is no way to tell which end is wrong
    ("Миронов и партнеры" 32456..30077, "Бытовка РНД" 4818..194).
  * 444 rows sit in 500..2999, which is impossible under either reading —
    far too cheap for roubles per m², absurd as thousands (500k-3M per m²).
  * The column also mixes scales outright (15 and 600 next to 22526 and
    32456), so cross-company comparison is meaningless even where each value
    might be individually defensible. That part is NOT fixed here; it is
    called out in the tool text instead.

A wrong price is worse than a missing one when someone is choosing a builder,
so contradictory and impossible rows lose both ends. Reversible: originals go
to price_per_sqm_min_orig / price_per_sqm_max_orig.

Dry run:  python3 clean_prices.py        Apply:  python3 clean_prices.py --apply
"""
import os
import sys

import psycopg2
import psycopg2.extras

APPLY = "--apply" in sys.argv

BAD = (
    "price_per_sqm_min IS NOT NULL AND ("
    "  (price_per_sqm_max IS NOT NULL AND price_per_sqm_max < price_per_sqm_min)"
    "  OR (price_per_sqm_min >= 500 AND price_per_sqm_min < 3000)"
    "  OR price_per_sqm_min >= 500000"
    "  OR price_per_sqm_min <= 0"
    ")"
)


def main():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "mcpuser"),
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ.get("DB_NAME", "mcpmarket"),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS price_per_sqm_min_orig numeric")
    cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS price_per_sqm_max_orig numeric")

    cur.execute("SELECT count(*) AS n FROM companies WHERE price_per_sqm_min IS NOT NULL")
    total = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM companies WHERE " + BAD)
    bad = cur.fetchone()["n"]
    cur.execute("SELECT left(name,30) AS name, price_per_sqm_min AS mn, price_per_sqm_max AS mx "
                "FROM companies WHERE " + BAD + " ORDER BY random() LIMIT 10")
    sample = cur.fetchall()

    print("mode: " + ("APPLY" if APPLY else "DRY RUN"))
    print("priced rows: %d | untrustworthy: %d (%.1f%%) | kept: %d"
          % (total, bad, 100.0 * bad / max(total, 1), total - bad))
    for r in sample:
        print("  %-30s %s .. %s" % (r["name"], r["mn"], r["mx"]))

    if APPLY and bad:
        cur.execute(
            "UPDATE companies SET "
            "price_per_sqm_min_orig = COALESCE(price_per_sqm_min_orig, price_per_sqm_min), "
            "price_per_sqm_max_orig = COALESCE(price_per_sqm_max_orig, price_per_sqm_max), "
            "price_per_sqm_min = NULL, price_per_sqm_max = NULL "
            "WHERE " + BAD)
        conn.commit()
        print("\ncleared %d price ranges (originals kept in *_orig)" % cur.rowcount)
    else:
        conn.rollback()
        print("\nnothing written (dry run)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
