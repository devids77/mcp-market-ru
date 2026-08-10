#!/usr/bin/env python3
"""Mark the house projects that were invented by scripts/full_parser.py.

gen_projects() (full_parser.py:95-115) never looked at a source page. For every
company it walked a hardcoded area list per category, took a hardcoded ₽/m²,
multiplied by a city coefficient, and derived floors/bedrooms/bathrooms as
arithmetic on the area:

    price = int(area * ppsm * mul)
    name  = f"{company} — {material.title()} {area}"
    desc  = f"Проект дома {area} кв.м от {company}, {city}. {fl} эт., {bd} спален. ..."

15 854 of 20 322 rows (78%) carry that exact signature. They are served to
agents as real offerings with a specific price, so an agent tells a user
"this contractor builds a 120 m² frame house for 4.4M ₽" — a figure the
contractor never quoted, sometimes attributed to a sales office or an estate
agency. Mark them source='generated' so the tools can exclude them; the rows
stay for analysis and the change is reversible.

Dry run:  python3 mark_generated_projects.py      Apply:  ... --apply
"""
import os
import sys

import psycopg2
import psycopg2.extras

APPLY = "--apply" in sys.argv

SIG = "description ~ '^Проект дома [0-9]+ кв\\.м от '"


def main():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "mcpuser"),
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ.get("DB_NAME", "mcpmarket"),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT COALESCE(source,'(null)') AS src, count(*) FROM projects GROUP BY 1 ORDER BY 2 DESC")
    print("mode: " + ("APPLY" if APPLY else "DRY RUN"))
    print("current source distribution:")
    for r in cur.fetchall():
        print("   %-14s %s" % (r["src"], r["count"]))

    cur.execute("SELECT count(*) AS n FROM projects")
    total = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM projects WHERE " + SIG)
    gen = cur.fetchone()["n"]
    print("\ntotal %d | generated signature %d (%.1f%%) | real %d"
          % (total, gen, 100.0 * gen / max(total, 1), total - gen))

    cur.execute("SELECT left(name,52) AS name, price FROM projects WHERE " + SIG
                + " ORDER BY random() LIMIT 6")
    for r in cur.fetchall():
        print("   %-52s %s" % (r["name"], r["price"]))

    if APPLY and gen:
        cur.execute("UPDATE projects SET source = 'generated' WHERE " + SIG)
        conn.commit()
        print("\nmarked %d rows source='generated'" % cur.rowcount)
    else:
        conn.rollback()
        print("\nnothing written (dry run)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
