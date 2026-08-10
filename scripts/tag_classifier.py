"""Tag classifier v1 (regex-based) — 2026-04-24.
Reads companies.name + companies.description, extracts tags[] from keyword taxonomy.
Usage: python3 tag_classifier.py [--dry N]  (N = sample size, default=all)
"""
import os, sys, re, argparse
import psycopg2
from psycopg2.extras import RealDictCursor

TAXONOMY = {
    "каркас":        [r"каркас", r"скандинавск", r"норвежск", r"финск.*дом"],
    "брус":          [r"\bбрус", r"брусов", r"клеен\w*\s*брус"],
    "кирпич":        [r"кирпич"],
    "газобетон":     [r"газобетон", r"газоблок", r"пеноблок", r"пенобетон"],
    "сип":           [r"\bсип\b", r"sip[- ]панел", r"сип[- ]панел"],
    "бревно":        [r"бревнч", r"оцилиндров", r"\bсруб", r"бревенч"],
    "коттедж":       [r"коттедж"],
    "таунхаус":      [r"таунхаус"],
    "баня":          [r"\bбан[яе]\b", r"бан[иь]"],
    "гараж":         [r"\bгараж"],
    "бытовка":       [r"бытовк", r"времянк"],
    "заборы":        [r"\bзабор", r"ограждени", r"ограждать"],
    "кровля":        [r"кровл", r"\bкрыш", r"шифер", r"металлочерепиц"],
    "фасад":         [r"фасад", r"сайдинг", r"обшивк.*фасад"],
    "отделка":       [r"отделк", r"отделочн"],
    "ремонт":        [r"ремонт"],
    "окна_двери":    [r"\bокн[а-я]", r"\bдвер[а-я]", r"стеклопакет"],
    "полы":          [r"\bпол[ы]", r"ламинат", r"паркет", r"линолеум"],
    "инженерка":     [r"сантехник", r"электрик", r"отоплен", r"водопровод", r"канализ", r"вентиляц", r"инженерн.*сет"],
    "ландшафт":      [r"ландшафт", r"озелен", r"благоустр"],
    "бассейн":       [r"бассейн"],
    "снос":          [r"\bснос", r"демонтаж"],
    "монтаж":        [r"монтаж"],
    "проектирование":[r"проектир", r"\bпроект.*дом"],
    "недвижимость":  [r"продаж.*недвиж", r"агентств.*недвиж", r"риелтор", r"риэлтор"],
    "строительство": [r"строительств", r"постройк", r"построить", r"под ключ"],
    "дом_под_ключ":  [r"под\s+ключ"],
    "малоэтажн":     [r"малоэтажн"],
    "многоэтажн":    [r"многоэтажн"],
}

# Some names contain a tag's keyword while describing a different business:
# "каркасно-тентовые сооружения" contains "каркас" but the company makes
# canopies, not houses. This mis-tagged half of the каркасные_дома category.
# A tag is withheld when any of its negative patterns matches.
NEGATIVE = {
    "каркас": [r"тент", r"навес", r"шат[её]р", r"бассейн", r"купол",
               r"\btent\b", r"торгов\w*\s+оборудован", r"спортивн\w*\s+оборудован"],
}

COMPILED = {tag: [re.compile(p, re.IGNORECASE) for p in patterns] for tag, patterns in TAXONOMY.items()}
NEG_COMPILED = {tag: [re.compile(p, re.IGNORECASE) for p in patterns] for tag, patterns in NEGATIVE.items()}

def classify(name: str, description: str) -> list[str]:
    text = f"{name or ''} {description or ''}"
    if not text.strip():
        return []
    tags = []
    for tag, patterns in COMPILED.items():
        if any(p.search(text) for p in patterns):
            if any(n.search(text) for n in NEG_COMPILED.get(tag, ())):
                continue
            tags.append(tag)
    return tags

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", type=int, default=0, help="Print classification for N samples, don't write")
    ap.add_argument("--commit", action="store_true", help="Actually write tags[] column")
    args = ap.parse_args()
    conn = psycopg2.connect(host="mcp-db", dbname="mcpmarket", user="mcpuser", password=os.environ["DB_PASSWORD"])
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, name, description FROM companies")
    rows = cur.fetchall()
    print(f"Total companies: {len(rows)}")
    stats = {tag: 0 for tag in TAXONOMY}
    samples = []
    for r in rows:
        tags = classify(r["name"], r["description"])
        for t in tags:
            stats[t] += 1
        if args.dry and len(samples) < args.dry:
            samples.append((r["name"][:40], tags))
        if args.commit:
            cur.execute("UPDATE companies SET tags = %s WHERE id = %s", (tags, r["id"]))
    if args.commit:
        conn.commit()
        print("COMMITTED tags[] for all rows")
    print("=== Stats per tag (>0 only) ===")
    for tag, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        if cnt > 0:
            print(f"  {tag:20s} {cnt}")
    if samples:
        print("=== Sample classifications ===")
        for name, tags in samples[:20]:
            print(f"  {name!r:45s} -> {tags}")
    conn.close()
