#!/usr/bin/env python3
"""Data-quality repair for the companies catalogue.

Two defects, both of which surface in the product's main query
("find me a frame-house contractor"):

  1. category='karkasnye_doma' is polluted with tent/awning/dome makers -
     the classifier matched the substring "karkas" and swallowed
     "karkasno-tentovye konstrukcii".
  2. Many `description` values were scraped from the wrong page (company
     directories, coupon sites, counterparty-check services), so they say
     nothing about the company.

Dry run by default; pass --apply to write.
"""
import os
import sys

import psycopg2
import psycopg2.extras

APPLY = "--apply" in sys.argv

# Names that mean "not a house builder" even when the text contains karkas.
# Latin 'tent' matters: "Tattent" slips past a Cyrillic-only filter.
TENT_PATTERNS = [
    "тент", "навес", "шатер", "шатёр", "бассейн", "купол", "tent",
    "торгового оборудования", "спортивного оборудования",
]

# Boilerplate proving the description came from an aggregator page.
JUNK_MARKERS = [
    "справочник организаций",
    "организации и фирмы",
    "каждый день новые акции",
    "проверка контрагента",
    "добавить компанию",
    "товары и услуги:",
    "отзывы о компаниях",
    "рейтинг организаций",
    "удобный и быстрый поиск на карте",
]


def like_any(column, patterns):
    clause = " OR ".join(f"{column} ILIKE %s" for _ in patterns)
    return f"({clause})", [f"%{p}%" for p in patterns]


def main():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "mcpuser"),
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ.get("DB_NAME", "mcpmarket"),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='companies'")
    cols = {r["column_name"] for r in cur.fetchall()}
    has_orig = "description_orig" in cols
    print("description_orig column:", "yes" if has_orig else "no")
    print("mode:", "APPLY" if APPLY else "DRY RUN", "\n")

    tent_sql, tent_params = like_any("name", TENT_PATTERNS)
    cur.execute(
        f"SELECT id, name FROM companies WHERE category = 'каркасные_дома' AND {tent_sql} ORDER BY name",
        tent_params,
    )
    tents = cur.fetchall()
    print(f"[1] tents mis-filed as каркасные_дома: {len(tents)}")
    for r in tents:
        print("      -", r["name"][:70])
    if APPLY and tents:
        ids = [r["id"] for r in tents]
        cur.execute(
            "UPDATE companies SET category = 'строительство', "
            "tags = ARRAY(SELECT DISTINCT unnest("
            "  array_remove(COALESCE(tags, '{}'), 'каркас') || ARRAY['тенты_навесы'])) "
            "WHERE id = ANY(%s::uuid[])",
            (ids,),
        )
        print("    -> recategorised", cur.rowcount)

    junk_sql, junk_params = like_any("description", JUNK_MARKERS)
    cur.execute(
        f"SELECT id, name, left(description, 90) AS d FROM companies "
        f"WHERE description IS NOT NULL AND {junk_sql} ORDER BY name",
        junk_params,
    )
    junk = cur.fetchall()
    print(f"\n[2] descriptions scraped from aggregator pages: {len(junk)}")
    for r in junk[:15]:
        print(f"      - {r['name'][:38]:38s} :: {r['d'][:60]}")
    if len(junk) > 15:
        print(f"      ... and {len(junk) - 15} more")
    if APPLY and junk:
        ids = [r["id"] for r in junk]
        if has_orig:
            cur.execute(
                "UPDATE companies SET description_orig = COALESCE(description_orig, description), "
                "description = NULL WHERE id = ANY(%s::uuid[])", (ids,))
        else:
            cur.execute("UPDATE companies SET description = NULL WHERE id = ANY(%s::uuid[])", (ids,))
        print("    -> cleared", cur.rowcount, "descriptions")

    if APPLY:
        conn.commit()
        print("\ncommitted")
    else:
        conn.rollback()
        print("\nnothing written (dry run) - rerun with --apply")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
