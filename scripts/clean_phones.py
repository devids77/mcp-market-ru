#!/usr/bin/env python3
"""Null company phone numbers that cannot exist in the Russian numbering plan.

About 39% of stored phones are fabricated: the 3-digit area code comes from
ranges that are simply not assigned (+7 (000) 000-00-00, +7 (102) ...,
+7 (250) ..., +7 (062) ...), or it is a Kazakh 6xx/7xx range attached to a
company whose city is Novosibirsk / Kazan / St Petersburg. Handing one of
those to a user is the worst thing this catalogue can do, and the company
page now publishes schema.org `telephone`, so the fake number ships as
structured data too.

Valid Russian area codes start with 3, 4, 8 or 9. Anything starting with
0, 1, 2, 5, 6 or 7 is not reachable from Russia.

Reversible: the original moves to phone_orig.

Dry run:  python3 clean_phones.py        Apply:  python3 clean_phones.py --apply
"""
import os
import sys

import psycopg2
import psycopg2.extras

APPLY = "--apply" in sys.argv

NORM = "regexp_replace(regexp_replace(phone, '[^0-9]', '', 'g'), '^8', '7')"
BAD_SQL = (
    "phone IS NOT NULL AND phone <> '' AND ("
    " length(" + NORM + ") <> 11"
    " OR substr(" + NORM + ", 2, 1) NOT IN ('3','4','8','9')"
    " OR " + NORM + " ~ '(.)\\1{6,}'"
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
    cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS phone_orig text")

    cur.execute("SELECT count(*) AS n FROM companies WHERE phone IS NOT NULL AND phone <> ''")
    total = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM companies WHERE " + BAD_SQL)
    bad = cur.fetchone()["n"]
    cur.execute("SELECT left(name,28) AS name, city, phone FROM companies WHERE "
                + BAD_SQL + " ORDER BY random() LIMIT 12")
    sample = cur.fetchall()

    print("mode: " + ("APPLY" if APPLY else "DRY RUN"))
    print("phones total: %d | unreachable: %d (%.1f%%)\n" % (total, bad, 100.0 * bad / max(total, 1)))
    for r in sample:
        print("  %-28s | %-18s | %s" % (r["name"], r["city"] or "", r["phone"]))

    if APPLY and bad:
        cur.execute("UPDATE companies SET phone_orig = COALESCE(phone_orig, phone), "
                    "phone = NULL WHERE " + BAD_SQL)
        conn.commit()
        print("\ncleared %d phones (originals kept in phone_orig)" % cur.rowcount)
    else:
        conn.rollback()
        print("\nnothing written (dry run)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
