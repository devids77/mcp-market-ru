
# ============================================================
# New MCP tools (added 2026-04-20): export_search_csv, smart_match, get_lead_status
# ============================================================

import csv as _csv
import io as _io
import re as _re
import json as _json


@mcp.tool()
def export_search_csv(
    entity: str = "companies",
    query: str = "",
    category: str = "",
    region: str = "",
    budget_max: float = 0,
    limit: int = 500,
) -> str:
    """
    Export search results as CSV text (UTF-8 with BOM, Excel-friendly).

    entity: 'companies' or 'projects'
    query: free-text search in name/description
    category, region: filter fields
    budget_max: for companies, cap on min_project_price
    limit: 1..2000 rows (default 500)

    Returns CSV text ready to save as .csv and open in Excel.
    """
    if entity not in ("companies", "projects"):
        return "ERROR: entity must be 'companies' or 'projects'"

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = {}
            conditions = ["1=1"]
            if query:
                conditions.append("(name ILIKE %(query)s OR description ILIKE %(query)s)")
                params["query"] = f"%{query}%"
            if category:
                conditions.append("(category = %(category)s)")
                params["category"] = category
            if region:
                conditions.append("(region ILIKE %(region)s OR city ILIKE %(region)s)")
                params["region"] = f"%{region}%"
            if budget_max > 0 and entity == "companies":
                conditions.append("(min_project_price <= %(budget)s OR min_project_price IS NULL)")
                params["budget"] = budget_max

            where = " AND ".join(conditions)
            params["lim"] = max(1, min(int(limit), 2000))

            if entity == "companies":
                cols = ["id", "name", "category", "region", "city",
                        "website", "phone", "rating", "reviews_count",
                        "projects_count", "price_per_sqm_min", "price_per_sqm_max",
                        "min_project_price", "max_project_price"]
                sql = f"SELECT {', '.join(cols)} FROM companies WHERE {where} ORDER BY rating DESC NULLS LAST LIMIT %(lim)s"
            else:
                cols = ["id", "name", "category", "region", "city",
                        "price_total", "area_sqm", "floors", "description"]
                sql = f"SELECT {', '.join(cols)} FROM projects WHERE {where} ORDER BY created_at DESC NULLS LAST LIMIT %(lim)s"

            cur.execute(sql, params)
            rows = cur.fetchall()

            buf = _io.StringIO()
            w = _csv.writer(buf, quoting=_csv.QUOTE_MINIMAL)
            w.writerow(cols)
            for r in rows:
                w.writerow([r.get(c, "") for c in cols])

            return "\ufeff" + buf.getvalue()
    finally:
        conn.close()


@mcp.tool()
def smart_match(brief: str, top_n: int = 5) -> str:
    """
    Natural-language contractor search. Pass a free-form Russian brief
    (e.g. "хочу каркасный дом 180 кв.м в Подмосковье до 15 млн") and get
    top-N matching contractors plus an explanation of how the brief was parsed.

    Returns JSON with: parsed filters, matches list, explanation.
    """
    text = brief.lower()

    area = 0.0
    m = _re.search(r"(\d{2,5})\s*(?:кв\.?\s*м|м2|м²|квадрат)", text)
    if m:
        area = float(m.group(1))

    budget = 0.0
    m = _re.search(r"(?:до|бюджет|не\s*больше)\s*(\d+(?:[.,]\d+)?)\s*млн", text)
    if m:
        budget = float(m.group(1).replace(",", ".")) * 1_000_000
    else:
        m = _re.search(r"(?:до|бюджет)\s*(\d{5,})\s*(?:руб|₽)?", text)
        if m:
            budget = float(m.group(1))

    region_map = {
        "подмосков": "Московская область", "московск": "Московская область",
        "москв": "Москва",
        "питер": "Санкт-Петербург", "спб": "Санкт-Петербург", "петербург": "Санкт-Петербург",
        "ленинград": "Ленинградская область", "ленобл": "Ленинградская область",
        "краснодар": "Краснодарский край", "кубан": "Краснодарский край",
        "сочи": "Краснодарский край",
        "новосибир": "Новосибирская область", "екатеринб": "Свердловская область",
        "казан": "Татарстан", "уфа": "Башкортостан", "тюмен": "Тюменская область",
        "красноярск": "Красноярский край", "челябинск": "Челябинская область",
        "ростов": "Ростовская область", "воронеж": "Воронежская область",
        "нижний новгород": "Нижегородская область", "самар": "Самарская область",
    }
    region = ""
    for key, val in region_map.items():
        if key in text:
            region = val
            break

    category_map = {
        "каркас": "Каркасные дома",
        "из бруса": "Дома из бруса", "брусов": "Дома из бруса",
        "кирпич": "Кирпичные дома",
        "газобетон": "Газобетонные дома", "газоблок": "Газобетонные дома",
        "пеноблок": "Блочные дома", "керамзит": "Блочные дома", "блочн": "Блочные дома",
        "сип": "СИП-дома",
        "бревен": "Бревенчатые дома", "сруб": "Бревенчатые дома",
        "бан": "Бани",
        "гараж": "Гаражи",
        "коттедж": "Коттеджи",
        "таунхаус": "Таунхаусы",
    }
    category = ""
    for key, val in category_map.items():
        if key in text:
            category = val
            break

    quality = "standard"
    if any(w in text for w in ["премиум", "люкс", "элит", "дорого", "топ"]):
        quality = "premium"
    elif any(w in text for w in ["эконом", "дешев", "недорого", "бюджетн"]):
        quality = "economy"

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = {}
            conditions = ["1=1"]
            if region:
                conditions.append("(region ILIKE %(region)s)")
                params["region"] = f"%{region}%"
            if category:
                conditions.append("(category ILIKE %(category)s)")
                params["category"] = f"%{category}%"
            if budget > 0:
                conditions.append("(min_project_price <= %(budget)s OR min_project_price IS NULL)")
                params["budget"] = budget

            params["lim"] = max(1, min(int(top_n), 20))
            where = " AND ".join(conditions)
            sql = f"""
                SELECT id, name, category, region, city, rating, reviews_count,
                       min_project_price, max_project_price, phone, website
                FROM companies
                WHERE {where}
                ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
                LIMIT %(lim)s
            """
            cur.execute(sql, params)
            matches = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    result = {
        "brief": brief,
        "parsed": {
            "region": region or None,
            "category": category or None,
            "area_sqm": area or None,
            "budget_rub": budget or None,
            "quality": quality,
        },
        "matches": matches,
        "explanation": (
            f"Разобрано: регион={region or 'любой'}, категория={category or 'любая'}, "
            f"площадь={area or '?'} кв.м, бюджет={budget or '?'} руб, класс={quality}. "
            f"Найдено {len(matches)} подрядчиков, сортировка по rating и числу отзывов."
        ),
    }
    return _json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def get_lead_status(lead_id: str, api_key: str) -> str:
    """
    Check the status of a lead created via request_quote.

    lead_id: UUID returned by request_quote
    api_key: the api_key used when the lead was created

    Returns JSON with status (new/contacted/won/lost), company info,
    contact fields, budget, timestamps.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, plan, is_active FROM api_keys WHERE key = %s", (api_key,))
            key_row = cur.fetchone()
            if not key_row or not key_row.get("is_active"):
                return _json.dumps({"error": "Invalid or inactive api_key"})

            cur.execute("""
                SELECT l.id, l.status, l.client_name, l.client_phone, l.client_email,
                       l.project_description, l.budget_from, l.budget_to, l.region,
                       l.category, l.created_at, l.sent_to_crm_at, l.crm_lead_id,
                       c.name AS company_name
                FROM leads l
                LEFT JOIN companies c ON c.id = l.company_id
                WHERE l.id::text = %s
            """, (lead_id,))
            row = cur.fetchone()
            if not row:
                return _json.dumps({"error": f"Lead {lead_id} not found"})

            return _json.dumps(dict(row), ensure_ascii=False, default=str)
    finally:
        conn.close()
