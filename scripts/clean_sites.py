#!/usr/bin/env python3
"""Null company `website` values that point at directories/aggregators, not
the company's own site. Reversible: the original moves to website_orig.

Dry run:  python3 clean_sites.py        Apply:  python3 clean_sites.py --apply
"""
import os, sys
import psycopg2, psycopg2.extras

APPLY = "--apply" in sys.argv

AGGREGATOR_RX = (
    r"spravker|2gis|etagi|cian|avito|domofond|yell\.ru|zoon\.ru|orgpage|"
    r"flamp|blizko|rusprofile|list-org|справоч|prodoctorov"
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
    cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS website_orig text")

    cur.execute(
        "SELECT name, website FROM companies "
        "WHERE website IS NOT NULL AND website <> '' AND website ~* %s "
        "ORDER BY random() LIMIT 15", (AGGREGATOR_RX,))
    sample = cur.fetchall()
    cur.execute(
        "SELECT count(*) AS n FROM companies "
        "WHERE website IS NOT NULL AND website <> '' AND website ~* %s", (AGGREGATOR_RX,))
    n = cur.fetchone()["n"]

    print(f"mode: {'APPLY' if APPLY else 'DRY RUN'}")
    print(f"aggregator websites matched: {n}\n")
    for r in sample:
        print(f"  {r['name'][:34]:34s} :: {r['website']}")

    if APPLY and n:
        cur.execute(
            "UPDATE companies SET website_orig = COALESCE(website_orig, website), "
            "website = NULL WHERE website IS NOT NULL AND website <> '' AND website ~* %s",
            (AGGREGATOR_RX,))
        conn.commit()
        print(f"\ncleared {cur.rowcount} websites (originals kept in website_orig)")
    else:
        conn.rollback()
        print("\nnothing written (dry run)")
    cur.close(); conn.close()


if __name__ == "__main__":
    main()
