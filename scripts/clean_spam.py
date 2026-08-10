#!/usr/bin/env python3
"""Clear scraped-aggregator / spam descriptions from the companies catalogue.

Reversible: spam text moves to description_orig, description is nulled, so the
company keeps its identity and the page falls back to a clean summary.

Dry run:  python3 clean_spam.py       Apply:  python3 clean_spam.py --apply
"""
import os, re, sys
import psycopg2, psycopg2.extras

APPLY = "--apply" in sys.argv

SPAM_MARKERS = [
    "этажи", "циан", "авито", "domofond", "юла", "n1.ru",
    "агентство недвижимости", "риэлтор", "риелтор",
    "весь спектр услуг в сфере сделок",
    "предложений по продаже", "предложения по продаже",
    "квартир в аренду", "квартиры в аренду", "снять квартиру",
    "розыгрыш квартир", "итоги розыгрыша",
    "справочник организаций", "добавить компанию", "добавить организацию",
    "проверка контрагента", "отзывы о компаниях", "рейтинг организаций",
    "каждый день новые акции", "товаров с фото",
    "бюллетень российских лидеров", "удобный и быстрый поиск на карте",
    "отзыв о компании", "оставить отзыв",
    "spravker", "справоч", "orgpage", "yell.ru", "zoon.ru", "flamp.ru", "blizko.ru",
]

def like_any(col, pats):
    clause = " OR ".join(f"{col} ILIKE %s" for _ in pats)
    return f"({clause})", [f"%{p}%" for p in pats]

def main():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "mcpuser"),
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ.get("DB_NAME", "mcpmarket"),
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS description_orig text")
    where, params = like_any("description", SPAM_MARKERS)
    cur.execute(
        f"SELECT id, name, category, left(regexp_replace(description,'\\s+',' ','g'),75) AS d "
        f"FROM companies WHERE description IS NOT NULL AND length(description)>0 AND {where} "
        f"ORDER BY random() LIMIT 20", params)
    sample = cur.fetchall()
    cur.execute(
        f"SELECT count(*) AS n FROM companies "
        f"WHERE description IS NOT NULL AND length(description)>0 AND {where}", params)
    n = cur.fetchone()["n"]
    print(f"mode: {'APPLY' if APPLY else 'DRY RUN'}")
    print(f"spam descriptions matched: {n}\n")
    for r in sample:
        print(f"  [{(r['category'] or '')[:16]:16s}] {r['name'][:30]:30s} :: {r['d']}")
    if APPLY and n:
        cur.execute(
            f"UPDATE companies SET description_orig = COALESCE(description_orig, description), "
            f"description = NULL WHERE description IS NOT NULL AND length(description)>0 AND {where}",
            params)
        conn.commit()
        print(f"\ncleared {cur.rowcount} descriptions (originals kept in description_orig)")
    else:
        conn.rollback()
        print("\nnothing written (dry run)")
    cur.close(); conn.close()

if __name__ == "__main__":
    main()
