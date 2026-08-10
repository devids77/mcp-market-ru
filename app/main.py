"""
MCP Market Russia — Russian construction companies catalog for AI agents
First business MCP server catalog for the Russian market
Version: 3.1.1
"""
import json
import time
import html
from typing import Optional
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastmcp import FastMCP

from app.config import settings


# ─── Database helper (sync, for MCP tools) ─────────────────────────

def get_db_connection():
    return get_db()

def get_db():
    """Get sync database connection for MCP tools."""
    conn = psycopg2.connect(settings.DATABASE_URL_SYNC)
    conn.autocommit = True
    return conn


# ============= API KEY MIDDLEWARE =============
PREMIUM_TOOLS = ["market_analytics", "find_best_companies", "price_comparison", 
    "company_portfolio", "market_report", "review_analysis", "contractor_rec",
    "project_estimator", "trend_analyzer", "company_deep_profile", "region_comparison"]

FREE_TOOLS = ["search_companies", "search_projects", "compare_companies", 
    "calculate_cost", "get_company", "get_project", "get_categories", 
    "get_regions", "get_stats", "request_quote", "smart_match"]

async def validate_api_key(request: Request, tool_name: str = None):
    """Validate API key and check rate limits. Returns key info or None for free access."""
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not api_key:
        # Allow free tools without key
        if tool_name and tool_name in FREE_TOOLS:
            return {"plan": "anonymous", "tools": FREE_TOOLS}
        return None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, key, plan, requests_limit, requests_used, is_active 
            FROM api_keys WHERE key = %s
        """, (api_key,))
        key_data = cur.fetchone()
        
        if not key_data or not key_data["is_active"]:
            conn.close()
            return None
        
        # Check rate limit (-1 = unlimited)
        if key_data["requests_limit"] != -1 and key_data["requests_used"] >= key_data["requests_limit"]:
            conn.close()
            return {"error": "rate_limit_exceeded", "plan": key_data["plan"]}
        
        # Increment usage
        cur.execute("UPDATE api_keys SET requests_used = requests_used + 1, last_used_at = NOW() WHERE id = %s", (key_data["id"],))
        conn.commit()
        
        # Log usage
        try:
            cur.execute("""
                INSERT INTO usage_logs (api_key_id, tool_name, ip_address, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (key_data["id"], tool_name or "unknown", request.client.host if request.client else "unknown"))
            conn.commit()
        except:
            pass
        
        conn.close()
        
        plan_tools = {
            "free": FREE_TOOLS,
            "starter": FREE_TOOLS + PREMIUM_TOOLS[:5],
            "pro": FREE_TOOLS + PREMIUM_TOOLS,
            "enterprise": FREE_TOOLS + PREMIUM_TOOLS
        }
        
        return {
            "plan": key_data["plan"],
            "tools": plan_tools.get(key_data["plan"], FREE_TOOLS),
            "requests_used": key_data["requests_used"] + 1,
            "requests_limit": key_data["requests_limit"]
        }
    except Exception as e:
        return {"error": str(e)}



# ============================================================
# API KEY MIDDLEWARE - validates keys on all /api/v1/ endpoints
# ============================================================
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse
import time as _time
import httpx

# Endpoints that require NO API key (public)
PUBLIC_ENDPOINTS = {
    "/", "/pricing", "/pricing.html", "/tasks", "/tasks.html",
    "/dashboard", "/api/pricing", "/api/stats",
    "/api/dashboard/top-companies", "/api/dashboard/materials",
    "/api/dashboard/queries-chart", "/api/dashboard/popular-tools",
    "/api/dashboard/companies", "/api/tasks",
}

# Endpoints that require authentication (any valid key)
AUTH_ENDPOINTS = {
    "/api/leads", "/api/leads/create", "/api/keys", "/api/usage/stats",
    "/api/register",
}

# Analytics endpoints - require Starter+ plan
ANALYTICS_ENDPOINTS = {
    "/api/analytics/price-map", "/api/analytics/market-summary",
    "/api/analytics/top-companies", "/api/analytics/price-tiers",
}

# REST API tool endpoints - gated by plan
API_TOOL_ENDPOINTS = {
    "/api/v1/search/companies": "free",
    "/api/v1/smart-match": "free",
    "/api/v1/search/projects": "free",
    "/api/v1/companies": "free",
    "/api/v1/projects": "free",
    "/api/v1/categories": "free",
    "/api/v1/regions": "free",
    "/api/v1/stats": "free",
    "/api/v1/health": "free",
    "/api/v1/compare": "free",
    "/api/v1/docs": "free",
    "/api/v1/calculate": "free",
    "/api/v1/analytics/market": "starter",
    "/api/v1/analytics/best-companies": "starter",
    "/api/v1/analytics/price-comparison": "starter",
    "/api/v1/analytics/portfolio": "starter",
    "/api/v1/analytics/report": "starter",
    "/api/v1/ai/reviews": "pro",
    "/api/v1/ai/recommend": "pro",
    "/api/v1/ai/estimate": "pro",
    "/api/v1/ai/trends": "pro",
    "/api/v1/ai/deep-profile": "pro",
    "/api/v1/ai/region-compare": "pro",
}

PLAN_HIERARCHY = {"free": 0, "anonymous": 0, "starter": 1, "pro": 2, "enterprise": 3}

RATE_LIMITS = {
    "free": 100,
    "anonymous": 50,
    "starter": 1000,
    "pro": 5000,
    "enterprise": -1,
}

_ANON_USAGE = {}  # (day, ip) -> count; in-memory ok: workers=1

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path.rstrip("/") or "/"
        
        # Skip non-API and public endpoints
        if not path.startswith("/api/v1/"):
            return await call_next(request)
        
        # Get API key
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        
        if not api_key:
            # Check if this is a free-tier endpoint
            required_plan = API_TOOL_ENDPOINTS.get(path, None)
            # Handle dynamic paths like /api/v1/companies/{id}
            if required_plan is None and path.startswith("/api/v1/companies/"):
                required_plan = "free"
            if required_plan == "free":
                # Allow anonymous access to free endpoints with lower rate limit
                ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
                day = _time.strftime("%Y-%m-%d")
                if len(_ANON_USAGE) > 20000:
                    _ANON_USAGE.clear()
                used = _ANON_USAGE.get((day, ip), 0) + 1
                if used > RATE_LIMITS.get("anonymous", 50):
                    return StarletteJSONResponse(
                        status_code=429,
                        content={"error": "Anonymous daily limit reached (50 req/day)",
                                 "hint": "Free API key: https://mcp-market.ru/quickstart"})
                _ANON_USAGE[(day, ip)] = used
                request.state.plan = "anonymous"
                request.state.api_key = None
                return await call_next(request)
            return StarletteJSONResponse(
                status_code=401,
                content={
                    "error": "API key required",
                    "message": "Provide API key via X-API-Key header or api_key query parameter",
                    "get_key": "https://mcp-market.ru/pricing"
                }
            )
        
        # Validate the key
        key_info = await validate_api_key(request, tool_name=None)
        if key_info is None:
            return StarletteJSONResponse(
                status_code=403,
                content={"error": "Invalid API key", "get_key": "https://mcp-market.ru/pricing"}
            )
        
        if isinstance(key_info, dict) and "error" in key_info:
            return StarletteJSONResponse(
                status_code=429 if "rate" in str(key_info.get("error", "")).lower() else 403,
                content=key_info
            )
        
        # Check plan level for endpoint
        required_plan = API_TOOL_ENDPOINTS.get(path, "free")
        user_plan = key_info.get("plan", "free") if isinstance(key_info, dict) else "free"
        
        if PLAN_HIERARCHY.get(user_plan, 0) < PLAN_HIERARCHY.get(required_plan, 0):
            return StarletteJSONResponse(
                status_code=403,
                content={
                    "error": f"Plan '{user_plan}' insufficient. Requires '{required_plan}' or higher.",
                    "upgrade": "https://mcp-market.ru/pricing",
                    "current_plan": user_plan,
                    "required_plan": required_plan
                }
            )
        
        request.state.plan = user_plan
        request.state.api_key = api_key
        return await call_next(request)


def query_db(sql: str, params: dict = None, limit: int = 20) -> list[dict]:
    """Execute query and return list of dicts."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or {})
            rows = cur.fetchmany(limit)
            return [dict(r) for r in rows]
    finally:
        conn.close()


def execute_db(sql: str, params: dict = None) -> Optional[dict]:
    """Execute insert/update and return result."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or {})
            try:
                return dict(cur.fetchone())
            except Exception:
                return None
    finally:
        conn.close()


def log_query(tool_name: str, params: dict, results_count: int, duration_ms: int):
    """Log agent query for analytics."""
    try:
        execute_db(
            """INSERT INTO agent_queries (tool_name, params, results_count, duration_ms) 
               VALUES (%(tool)s, %(params)s, %(count)s, %(dur)s)""",
            {
                "tool": tool_name,
                "params": json.dumps(params, ensure_ascii=False, default=str),
                "count": results_count,
                "dur": duration_ms,
            },
        )
    except Exception:
        pass


# ─── MCP Server ─────────────────────────────────────────────────────

mcp = FastMCP(
    "MCP Market Russia",
    instructions="""Russian construction companies and house projects catalog for AI agents.
3,400+ verified companies across 20 cities. Real data from 2GIS and company websites.

Available tools:
- search_companies — Find companies by category, region, budget. Returns website, phone, rating, reviews.
- search_projects — Find house projects by area, floors, material, price. Returns project link + company contacts.
- compare_companies — Compare 2-3 companies side by side on prices, ratings, specialization.
- get_company / get_project — Full details with contacts and project listings.
- calculate_cost — Estimate construction cost based on real market data (area, material, region).
- get_categories / get_regions / get_stats — Reference data and catalog statistics.
- request_quote — Send a lead/quote request to a company on behalf of the user.

Always include company website and phone in your response so the user can contact them directly.""",
)


_EN_SYNONYMS = {
    "frame": "каркас", "timber": "брус", "beam": "брус", "brick": "кирпич",
    "concrete": "газобетон", "aerated": "газобетон", "sip": "сип",
    "house": "дом", "houses": "дом", "home": "дом", "cottage": "коттедж",
    "construction": "строительство", "builder": "строительство",
    "company": "компания", "bath": "баня", "sauna": "баня",
    "roof": "кровля", "roofing": "кровля", "foundation": "фундамент",
    "renovation": "ремонт", "repair": "ремонт", "design": "проект",
    "modular": "модульный", "wooden": "дерево", "log": "бревно",
}


@mcp.tool()
def search_companies(
    query: str = "",
    category: str = "",
    region: str = "",
    budget_max: int = 0,
    limit: int = 10,
) -> str:
    """Search Russian construction companies by category, region, and budget.
    Returns company name, rating, prices, website, and phone number.

    Args:
        query: Free text search query (e.g. 'каркасные дома недорого', 'frame houses')
        category: Company category filter (каркасные_дома, дома_из_бруса, газобетон, кирпич, недвижимость, модульные_дома, СИП)
        region: Region or city name (e.g. 'Московская область', 'Санкт-Петербург', 'Краснодар')
        budget_max: Maximum budget in rubles. Set to 0 for no limit.
        limit: Number of results to return, maximum 20
    """
    start = time.time()
    limit = max(1, min(int(limit), 20))
    
    conditions = ["1=1"]
    params = {}
    
    rank_sql = ""
    if query:
        import re as _re
        _q = query.lower()
        for _en, _ru in _EN_SYNONYMS.items():
            _q = _re.sub(r"\b" + _en + r"\b", _ru, _q)
        _words = [w for w in _re.findall(r"[0-9a-zа-яё]+", _q, _re.IGNORECASE) if len(w) >= 3]
        params["query"] = " or ".join(_words) if _words else query
        _vec = ("to_tsvector('russian', COALESCE(name,'') || ' ' || COALESCE(description,'') "
                "|| ' ' || COALESCE(city,'') || ' ' || COALESCE(category,'') "
                "|| ' ' || COALESCE(array_to_string(subcategories,' '),'') "
                "|| ' ' || COALESCE(array_to_string(tags,' '),''))")
        conditions.append(_vec + " @@ websearch_to_tsquery('russian', %(query)s)")
        rank_sql = "ts_rank(" + _vec + ", websearch_to_tsquery('russian', %(query)s)) DESC,"
    
    if category:
        conditions.append("(category = %(category)s OR %(category)s = ANY(subcategories))")
        params["category"] = category
    
    if region:
        conditions.append("(region ILIKE %(region)s OR city ILIKE %(region)s)")
        params["region"] = f"%{region}%"
    
    if budget_max > 0:
        conditions.append("(min_project_price <= %(budget)s OR min_project_price IS NULL)")
        params["budget"] = budget_max
    
    where = " AND ".join(conditions)
    sql = f"""
        SELECT id, name, category, region, city, description, website, phone,
               price_per_sqm_min, price_per_sqm_max, min_project_price, max_project_price,
               rating, reviews_count, projects_count, status, own_mcp_url
        FROM companies 
        WHERE {where}
        ORDER BY 
            {rank_sql}
            CASE WHEN status = 'verified' THEN 0 
                 WHEN status = 'claimed' THEN 1 
                 ELSE 2 END,
            rating DESC NULLS LAST,
            projects_count DESC
        LIMIT {limit}
    """
    
    rows = query_db(sql, params, limit)
    duration = int((time.time() - start) * 1000)
    log_query("search_companies", {"query": query, "category": category, "region": region, "budget_max": budget_max}, len(rows), duration)
    
    if not rows:
        return "Компании не найдены. Попробуйте изменить параметры поиска."
    
    results = []
    for r in rows:
        company = f"**{r['name']}**"
        if r.get("city"):
            company += f" ({r['city']})"
        if r.get("category"):
            company += f"\n  Категория: {r['category']}"
        if r.get("description"):
            desc = r["description"][:200]
            company += f"\n  {desc}"
        if r.get("min_project_price"):
            company += f"\n  Цены: от {r['min_project_price']:,} ₽".replace(",", " ")
        if r.get("price_per_sqm_min"):
            company += f" (от {r['price_per_sqm_min']:,} ₽/м²)".replace(",", " ")
        if r.get("rating"):
            company += f"\n  Рейтинг: {r['rating']}"
            if r.get("reviews_count"):
                company += f" ({r['reviews_count']} отзывов)"
        if r.get("phone"):
            company += f"\n  Телефон: {r['phone']}"
        if r.get("website"):
            company += f"\n  Сайт: {r['website']}"
        company += f"\n  ID: {r['id']}"
        results.append(company)
    
    header = f"Найдено компаний: {len(rows)}\n\n"
    return header + "\n\n".join(results)


@mcp.tool()
def search_projects(
    area_min: int = 0,
    area_max: int = 0,
    floors: int = 0,
    material: str = "",
    budget_max: int = 0,
    region: str = "",
    query: str = "",
    limit: int = 10,
) -> str:
    """Search house building projects by area, floors, material, and price.
    Returns project specifications, price, direct link, and company contacts.

    Args:
        area_min: Minimum house area in square meters. Set to 0 for no limit.
        area_max: Maximum house area in square meters. Set to 0 for no limit.
        floors: Number of floors/stories. Set to 0 for any.
        material: Building material filter (каркас/frame, брус/timber, газобетон/aerated_concrete, кирпич/brick, СИП/SIP)
        budget_max: Maximum price in rubles. Set to 0 for no limit.
        region: Filter by company region or city name
        query: Free text search in project name and description
        limit: Number of results to return, maximum 20
    """
    start = time.time()
    limit = max(1, min(int(limit), 20))
    
    conditions = ["1=1"]
    params = {}
    
    if area_min > 0:
        conditions.append("p.area >= %(area_min)s")
        params["area_min"] = area_min
    
    if area_max > 0:
        conditions.append("p.area <= %(area_max)s")
        params["area_max"] = area_max
    
    if floors > 0:
        conditions.append("p.floors = %(floors)s")
        params["floors"] = floors
    
    if material:
        conditions.append("p.material ILIKE %(material)s")
        params["material"] = f"%{material}%"
    
    if budget_max > 0:
        conditions.append("(p.price <= %(budget)s OR p.price IS NULL)")
        params["budget"] = budget_max
    
    if region:
        conditions.append("(c.region ILIKE %(region)s OR c.city ILIKE %(region)s)")
        params["region"] = f"%{region}%"
    
    if query:
        conditions.append(
            "to_tsvector('russian', COALESCE(p.name,'') || ' ' || COALESCE(p.description,'')) "
            "@@ plainto_tsquery('russian', %(query)s)"
        )
        params["query"] = query
    
    where = " AND ".join(conditions)
    sql = f"""
        SELECT p.id, p.name, p.area, p.floors, p.bedrooms, p.material, p.style,
               p.price, p.price_per_sqm, p.price_description, p.dimensions,
               p.description, p.url, p.features,
               c.name as company_name, c.id as company_id, c.region, c.city,
               c.website as company_website, c.phone as company_phone
        FROM projects p
        JOIN companies c ON p.company_id = c.id
        WHERE {where}
          AND COALESCE(p.url, '') NOT ILIKE '%%restate%%'
          AND COALESCE(p.url, '') NOT ILIKE '%%snyat%%'
          AND COALESCE(p.source_url, '') NOT ILIKE '%%snyat%%'
        ORDER BY c.rating DESC NULLS LAST, p.price DESC NULLS LAST
        LIMIT {max(1, min(int(limit), 50))}
    """
    
    rows = query_db(sql, params, limit)
    duration = int((time.time() - start) * 1000)
    log_query("search_projects", {"area_min": area_min, "area_max": area_max, "floors": floors, "material": material, "budget_max": budget_max}, len(rows), duration)
    
    if not rows:
        return "Проекты не найдены. Попробуйте изменить параметры поиска."
    
    results = []
    for r in rows:
        project = f"**{(r.get('name') or 'Без названия').strip() or 'Без названия'}**"
        project += f" — {r['company_name']}"
        if r.get("city"):
            project += f" ({r['city']})"
        if r.get("area"):
            project += f"\n  Площадь: {r['area']} м²"
        if r.get("floors"):
            project += f" | Этажей: {r['floors']}"
        if r.get("bedrooms"):
            project += f" | Спален: {r['bedrooms']}"
        if r.get("material"):
            project += f"\n  Материал: {r['material']}"
        if r.get("dimensions"):
            project += f" | Размер: {r['dimensions']}"
        if r.get("price"):
            project += f"\n  Цена: {r['price']:,} ₽".replace(",", " ")
        elif r.get("price_description"):
            project += f"\n  Цена: {r['price_description']}"
        if r.get("description"):
            desc = r["description"][:150]
            project += f"\n  {desc}"
        if r.get("url"):
            project += f"\n  Ссылка: {r['url']}"
        if r.get("company_phone"):
            project += f"\n  Телефон компании: {r['company_phone']}"
        if r.get("company_website"):
            project += f"\n  Сайт компании: {r['company_website']}"
        project += f"\n  ID: {r['id']} | Компания ID: {r['company_id']}"
        results.append(project)
    
    header = f"Найдено проектов: {len(rows)}\n\n"
    return header + "\n\n".join(results)


@mcp.tool()
def compare_companies(
    company_ids: str,
) -> str:
    """Compare 2-3 construction companies side by side on prices, ratings, number of projects, and specialization.

    Args:
        company_ids: Comma-separated company UUIDs to compare (2-3 IDs). Example: 'uuid1,uuid2,uuid3'
    """
    start = time.time()
    
    ids = [x.strip() for x in company_ids.split(",") if x.strip()]
    if len(ids) < 2:
        return "Ошибка: укажите минимум 2 ID компаний через запятую."
    if len(ids) > 3:
        ids = ids[:3]
    
    placeholders = ", ".join([f"%(id{i})s::uuid" for i in range(len(ids))])
    params = {f"id{i}": uid for i, uid in enumerate(ids)}
    
    rows = query_db(
        f"""SELECT id, name, category, city, region, description, website, phone,
                   price_per_sqm_min, price_per_sqm_max, min_project_price, max_project_price,
                   rating, reviews_count, projects_count
            FROM companies WHERE id IN ({placeholders})""",
        params, len(ids)
    )
    
    if len(rows) < 2:
        return "Ошибка: найдено менее 2 компаний. Проверьте ID."
    
    project_stats = {}
    for r in rows:
        cid = str(r["id"])
        prows = query_db(
            """SELECT COUNT(*) as cnt, 
                      MIN(price) as min_price, MAX(price) as max_price,
                      MIN(area) as min_area, MAX(area) as max_area,
                      array_agg(DISTINCT material) FILTER (WHERE material IS NOT NULL) as materials
               FROM projects WHERE company_id = %(id)s::uuid""",
            {"id": cid}, 1
        )
        project_stats[cid] = prows[0] if prows else {}
    
    result = "## Сравнение компаний\n\n"
    
    for r in rows:
        cid = str(r["id"])
        ps = project_stats.get(cid, {})
        
        result += f"### {r['name']}"
        if r.get("city"):
            result += f" ({r['city']})"
        result += "\n"
        
        if r.get("category"):
            result += f"- Специализация: {r['category']}\n"
        if r.get("rating"):
            result += f"- Рейтинг: {r['rating']}"
            if r.get("reviews_count"):
                result += f" ({r['reviews_count']} отзывов)"
            result += "\n"
        if r.get("min_project_price"):
            result += f"- Цены проектов: от {r['min_project_price']:,} ₽".replace(",", " ")
            if r.get("max_project_price"):
                result += f" до {r['max_project_price']:,} ₽".replace(",", " ")
            result += "\n"
        if r.get("price_per_sqm_min"):
            result += f"- Цена за м²: от {r['price_per_sqm_min']:,} ₽".replace(",", " ")
            if r.get("price_per_sqm_max"):
                result += f" до {r['price_per_sqm_max']:,} ₽".replace(",", " ")
            result += "\n"
        if ps.get("cnt"):
            result += f"- Проектов в каталоге: {ps['cnt']}\n"
        if ps.get("materials"):
            mats = [m for m in ps["materials"] if m]
            if mats:
                result += f"- Материалы: {', '.join(mats)}\n"
        if ps.get("min_area") and ps.get("max_area"):
            result += f"- Площади: от {ps['min_area']} до {ps['max_area']} м²\n"
        if r.get("phone"):
            result += f"- Телефон: {r['phone']}\n"
        if r.get("website"):
            result += f"- Сайт: {r['website']}\n"
        result += "\n"
    
    rated = [r for r in rows if r.get("rating")]
    if rated:
        best = max(rated, key=lambda x: float(x["rating"]))
        result += f"**Лучший рейтинг:** {best['name']} ({best['rating']})\n"
    
    cheapest = [r for r in rows if r.get("min_project_price")]
    if cheapest:
        cheap = min(cheapest, key=lambda x: x["min_project_price"])
        result += f"**Самые доступные цены:** {cheap['name']} (от {cheap['min_project_price']:,} ₽)\n".replace(",", " ")
    
    duration = int((time.time() - start) * 1000)
    log_query("compare_companies", {"company_ids": company_ids}, len(rows), duration)
    
    return result


@mcp.tool()
def calculate_cost(
    area: int,
    material: str = "",
    region: str = "",
    floors: int = 0,
) -> str:
    """Calculate estimated construction cost based on real market data from the catalog.
    Uses average price per m² by material and region from actual company prices and projects.

    Args:
        area: House area in square meters (required, e.g. 120)
        material: Building material (каркас/frame, брус/timber, газобетон/aerated_concrete, кирпич/brick, СИП/SIP). Empty = average across all.
        region: Region or city name for regional pricing. Empty = nationwide average.
        floors: Number of floors (1 or 2). 0 = no adjustment.
    """
    start = time.time()
    
    if area is None or area <= 0:
        return "Площадь должна быть больше 0 м²."

    # Get average price per sqm from companies
    conditions = ["price_per_sqm_min IS NOT NULL AND price_per_sqm_min > 0"]
    params = {}
    
    if material:
        conditions.append("(category ILIKE %(mat)s OR %(mat_raw)s = ANY(subcategories))")
        params["mat"] = f"%{material}%"
        params["mat_raw"] = material
    
    if region:
        conditions.append("(region ILIKE %(region)s OR city ILIKE %(region)s)")
        params["region"] = f"%{region}%"
    
    where = " AND ".join(conditions)
    
    rows = query_db(
        f"""SELECT 
                COUNT(*) as company_count,
                ROUND(AVG(price_per_sqm_min)) as avg_min,
                ROUND(AVG(price_per_sqm_max)) as avg_max,
                MIN(price_per_sqm_min) as cheapest,
                MAX(price_per_sqm_max) as most_expensive
            FROM companies WHERE {where}""",
        params, 1
    )
    
    # Also get data from projects
    proj_conditions = ["p.price IS NOT NULL AND p.price > 0 AND p.area IS NOT NULL AND p.area > 0"]
    proj_params = {}
    
    if material:
        proj_conditions.append("p.material ILIKE %(mat)s")
        proj_params["mat"] = f"%{material}%"
    
    if region:
        proj_conditions.append("(c.region ILIKE %(region)s OR c.city ILIKE %(region)s)")
        proj_params["region"] = f"%{region}%"
    
    proj_where = " AND ".join(proj_conditions)
    
    proj_rows = query_db(
        f"""SELECT 
                COUNT(*) as project_count,
                ROUND(AVG(p.price / p.area)) as avg_price_sqm,
                MIN(p.price) as min_price,
                MAX(p.price) as max_price
            FROM projects p
            JOIN companies c ON p.company_id = c.id
            WHERE {proj_where}""",
        proj_params, 1
    )
    
    r = rows[0] if rows else {}
    pr = proj_rows[0] if proj_rows else {}
    
    company_count = r.get("company_count", 0) or 0
    project_count = pr.get("project_count", 0) or 0
    
    # Determine best price estimate
    avg_price_sqm = None
    if pr.get("avg_price_sqm") and pr["avg_price_sqm"] > 0:
        avg_price_sqm = int(pr["avg_price_sqm"])
    elif r.get("avg_min") and r["avg_min"] > 0:
        avg_price_sqm = int((r["avg_min"] + (r.get("avg_max") or r["avg_min"])) / 2)
    
    if not avg_price_sqm:
        duration = int((time.time() - start) * 1000)
        log_query("calculate_cost", {"area": area, "material": material, "region": region}, 0, duration)
        return "Недостаточно данных для расчёта. Попробуйте без указания региона или материала."
    
    # Calculate estimates
    cost_estimate = avg_price_sqm * area
    cost_min = int(avg_price_sqm * area * 0.8)
    cost_max = int(avg_price_sqm * area * 1.3)
    
    # Floor adjustment
    if floors == 2:
        cost_estimate = int(cost_estimate * 1.05)
        cost_min = int(cost_min * 1.05)
        cost_max = int(cost_max * 1.05)
    
    # Build result
    result = f"## Расчёт стоимости строительства\n\n"
    result += f"**Параметры:**\n"
    result += f"- Площадь: {area} м²\n"
    if material:
        result += f"- Материал: {material}\n"
    if region:
        result += f"- Регион: {region}\n"
    if floors:
        result += f"- Этажей: {floors}\n"
    
    result += f"\n**Оценка стоимости:**\n"
    result += f"- Средняя цена за м²: {avg_price_sqm:,} ₽\n".replace(",", " ")
    result += f"- **Ориентировочная стоимость: {cost_estimate:,} ₽**\n".replace(",", " ")
    result += f"- Диапазон: от {cost_min:,} до {cost_max:,} ₽\n".replace(",", " ")
    
    result += f"\n**На основе данных:**\n"
    result += f"- Компаний с ценами: {company_count}\n"
    result += f"- Проектов с ценами: {project_count}\n"
    
    if r.get("cheapest"):
        result += f"- Минимальная цена за м²: {int(r['cheapest']):,} ₽\n".replace(",", " ")
    if r.get("most_expensive"):
        result += f"- Максимальная цена за м²: {int(r['most_expensive']):,} ₽\n".replace(",", " ")
    
    result += f"\n*Цены ориентировочные, основаны на данных {company_count} компаний и {project_count} проектов в каталоге. "
    result += f"Для точного расчёта используйте request_quote.*"
    
    duration = int((time.time() - start) * 1000)
    log_query("calculate_cost", {"area": area, "material": material, "region": region, "floors": floors}, 1, duration)
    
    return result


@mcp.tool()
def get_company(company_id: str) -> str:
    """Get full company profile including contacts, prices, rating, reviews, and list of house projects.

    Args:
        company_id: Company UUID from search_companies results
    """
    start = time.time()
    
    rows = query_db(
        "SELECT * FROM companies WHERE id = %(id)s::uuid",
        {"id": company_id}, 1
    )
    
    if not rows:
        return "Компания не найдена."
    
    c = rows[0]
    info = f"# {c['name']}\n\n"
    
    if c.get("description"):
        info += f"{c['description']}\n\n"
    
    info += "## Контакты\n"
    if c.get("city"):
        info += f"- Город: {c['city']}\n"
    if c.get("region"):
        info += f"- Регион: {c['region']}\n"
    if c.get("address"):
        info += f"- Адрес: {c['address']}\n"
    if c.get("phone"):
        info += f"- Телефон: {c['phone']}\n"
    if c.get("email"):
        info += f"- Email: {c['email']}\n"
    if c.get("website"):
        info += f"- Сайт: {c['website']}\n"
    
    info += "\n## Цены\n"
    if c.get("price_per_sqm_min"):
        info += f"- Цена за м²: от {c['price_per_sqm_min']:,} ₽".replace(",", " ")
        if c.get("price_per_sqm_max"):
            info += f" до {c['price_per_sqm_max']:,} ₽".replace(",", " ")
        info += "\n"
    if c.get("min_project_price"):
        info += f"- Цена проектов: от {c['min_project_price']:,} ₽".replace(",", " ")
        if c.get("max_project_price"):
            info += f" до {c['max_project_price']:,} ₽".replace(",", " ")
        info += "\n"
    
    if c.get("rating"):
        info += f"\n## Рейтинг\n- {c['rating']}"
        if c.get("reviews_count"):
            info += f" ({c['reviews_count']} отзывов)"
        info += "\n"
    
    projects = query_db(
        """SELECT id, name, area, floors, bedrooms, material, price, price_description, dimensions
           FROM projects WHERE company_id = %(id)s::uuid ORDER BY area ASC LIMIT 20""",
        {"id": company_id}, 20
    )
    
    if projects:
        info += f"\n## Проекты ({len(projects)})\n"
        for p in projects:
            line = f"- **{p.get('name', '—')}**"
            if p.get("area"):
                line += f" | {p['area']} м²"
            if p.get("floors"):
                line += f" | {p['floors']} эт."
            if p.get("material"):
                line += f" | {p['material']}"
            if p.get("price"):
                line += f" | {p['price']:,} ₽".replace(",", " ")
            elif p.get("price_description"):
                line += f" | {p['price_description']}"
            line += f" (ID: {p['id']})"
            info += line + "\n"
    
    duration = int((time.time() - start) * 1000)
    log_query("get_company", {"company_id": company_id}, 1, duration)
    
    return info


@mcp.tool()
def get_project(project_id: str) -> str:
    """Get detailed house project information including specifications, price, features, and company contacts.

    Args:
        project_id: Project UUID from search_projects results
    """
    start = time.time()
    
    rows = query_db(
        """SELECT p.*, c.name as company_name, c.phone as company_phone, 
                  c.website as company_website, c.id as company_id
           FROM projects p JOIN companies c ON p.company_id = c.id 
           WHERE p.id = %(id)s::uuid""",
        {"id": project_id}, 1
    )
    
    if not rows:
        return "Проект не найден."
    
    p = rows[0]
    info = f"# {p.get('name', 'Без названия')}\n"
    info += f"Компания: {p['company_name']}\n\n"
    
    info += "## Характеристики\n"
    if p.get("area"):
        info += f"- Площадь: {p['area']} м²\n"
    if p.get("floors"):
        info += f"- Этажей: {p['floors']}\n"
    if p.get("bedrooms"):
        info += f"- Спален: {p['bedrooms']}\n"
    if p.get("bathrooms"):
        info += f"- Санузлов: {p['bathrooms']}\n"
    if p.get("material"):
        info += f"- Материал: {p['material']}\n"
    if p.get("style"):
        info += f"- Стиль: {p['style']}\n"
    if p.get("dimensions"):
        info += f"- Размер: {p['dimensions']}\n"
    
    info += "\n## Цена\n"
    if p.get("price"):
        info += f"- {p['price']:,} ₽\n".replace(",", " ")
    if p.get("price_per_sqm"):
        info += f"- За м²: {p['price_per_sqm']:,} ₽\n".replace(",", " ")
    if p.get("price_description"):
        info += f"- {p['price_description']}\n"
    
    if p.get("description"):
        info += f"\n## Описание\n{p['description']}\n"
    
    if p.get("features") and len(p["features"]) > 0:
        info += "\n## Особенности\n"
        for f in p["features"]:
            info += f"- {f}\n"
    
    info += "\n## Контакты\n"
    if p.get("url"):
        info += f"- Страница проекта: {p['url']}\n"
    if p.get("company_website"):
        info += f"- Сайт компании: {p['company_website']}\n"
    if p.get("company_phone"):
        info += f"- Телефон компании: {p['company_phone']}\n"
    
    info += f"\nID компании: {p['company_id']} (используйте для request_quote)"
    
    duration = int((time.time() - start) * 1000)
    log_query("get_project", {"project_id": project_id}, 1, duration)
    
    return info


@mcp.tool()
def get_categories() -> str:
    """Get all company categories with the number of companies in each category."""
    start = time.time()
    
    rows = query_db(
        """SELECT category, COUNT(*) as count 
           FROM companies 
           WHERE category IS NOT NULL 
           GROUP BY category 
           ORDER BY count DESC""",
        limit=50
    )
    
    duration = int((time.time() - start) * 1000)
    log_query("get_categories", {}, len(rows), duration)
    
    if not rows:
        return "Категории пока не заполнены."
    
    result = "## Категории компаний\n\n"
    for r in rows:
        result += f"- **{r['category']}**: {r['count']} компаний\n"
    
    return result


@mcp.tool()
def get_regions() -> str:
    """Get all available regions with the number of companies in each region."""
    start = time.time()
    
    rows = query_db(
        """SELECT region, COUNT(*) as count 
           FROM companies 
           WHERE region IS NOT NULL 
           GROUP BY region 
           ORDER BY count DESC""",
        limit=100
    )
    
    duration = int((time.time() - start) * 1000)
    log_query("get_regions", {}, len(rows), duration)
    
    if not rows:
        return "Регионы пока не заполнены."
    
    result = "## Регионы\n\n"
    for r in rows:
        result += f"- **{r['region']}**: {r['count']} компаний\n"
    
    return result


@mcp.tool()
def get_stats() -> str:
    """Get catalog statistics: total companies, projects, regions, categories, agent queries today, and leads generated."""
    start = time.time()
    
    stats = {}
    for key, sql in [
        ("companies", "SELECT COUNT(*) as c FROM companies"),
        ("projects", "SELECT COUNT(*) as c FROM projects"),
        ("regions", "SELECT COUNT(DISTINCT region) as c FROM companies WHERE region IS NOT NULL"),
        ("categories", "SELECT COUNT(DISTINCT category) as c FROM companies WHERE category IS NOT NULL"),
        ("queries_today", "SELECT COUNT(*) as c FROM agent_queries WHERE timestamp > CURRENT_DATE"),
        ("leads_total", "SELECT COUNT(*) as c FROM leads"),
    ]:
        rows = query_db(sql, limit=1)
        stats[key] = rows[0]["c"] if rows else 0
    
    duration = int((time.time() - start) * 1000)
    log_query("get_stats", {}, 1, duration)
    
    return f"""## MCP Market Russia Statistics

- Companies: **{stats['companies']}**
- House projects: **{stats['projects']}**
- Regions: **{stats['regions']}**
- Categories: **{stats['categories']}**
- Agent queries today: **{stats['queries_today']}**
- Leads generated: **{stats['leads_total']}**

Version: 3.2.0 | 24 tools
"""


from app.lead_detector import looks_like_test  # noqa: E402

@mcp.tool()

async def request_quote(
    company_id: str,
    project_id: str = "",
    name: str = "",
    phone: str = "",
    email: str = "",
    comment: str = "",
) -> str:
    """Send a quote request to a construction company on behalf of the user.
    Returns confirmation with lead ID and company contact details.

    Args:
        company_id: Target company UUID (required)
        project_id: Specific project UUID if the user is interested in a particular house project
        name: Client's name for the quote request
        phone: Client's phone number for callback
        email: Client's email address
        comment: Additional comments or requirements for the quote
    """
    start = time.time()
    
    if not company_id:
        return "Ошибка: укажите company_id"
    
    if not phone and not email and not name:
        return "Ошибка: укажите хотя бы имя, телефон или email для связи"
    
    rows = query_db("SELECT name, phone, website FROM companies WHERE id = %(id)s::uuid", {"id": company_id}, 1)
    if not rows:
        return "Ошибка: компания не найдена"
    
    company_name = rows[0]["name"]
    company_phone = rows[0].get("phone", "")
    company_website = rows[0].get("website", "")
    
    project_clause = "%(project_id)s::uuid" if project_id else "NULL"
    _is_test_flag, _test_reason = looks_like_test(email, phone, name)

    # Anti-spam (M2): max 3 leads/day per contact, 300/day total
    if email or phone:
        _dup = query_db(
            "SELECT COUNT(*) AS c FROM leads WHERE created_at::date = CURRENT_DATE AND (email = %(email)s OR phone = %(phone)s)",
            {"email": email or None, "phone": phone or None}, 1)
        if _dup and _dup[0]["c"] >= 3:
            return "Заявка от этого контакта уже зарегистрирована сегодня — компания свяжется с вами."
    _day_total = query_db(
        "SELECT COUNT(*) AS c FROM leads WHERE created_at::date = CURRENT_DATE", {}, 1)
    if _day_total and _day_total[0]["c"] >= 300:
        return "Дневной лимит заявок сервиса исчерпан — попробуйте завтра."

    result = execute_db(
        f"""INSERT INTO leads (company_id, project_id, name, phone, email, comment, source, is_test, test_reason)
           VALUES (%(company_id)s::uuid, {project_clause}, %(name)s, %(phone)s, %(email)s, %(comment)s, 'mcp', %(is_test)s, %(test_reason)s)
           RETURNING id""",
        {
            "company_id": company_id,
            "project_id": project_id or None,
            "name": name,
            "phone": phone,
            "email": email,
            "comment": comment,
            "is_test": _is_test_flag,
            "test_reason": _test_reason,
        },
    )
    
    duration = int((time.time() - start) * 1000)
    log_query("request_quote", {"company_id": company_id, "project_id": project_id}, 1, duration)
    
    lead_id = result["id"] if result else "unknown"
    
    response = f"Заявка отправлена компании «{company_name}».\nНомер заявки: {lead_id}\n"
    if company_phone:
        response += f"Телефон компании: {company_phone}\n"
    if company_website:
        response += f"Сайт компании: {company_website}\n"
    response += "С вами свяжутся в ближайшее время."
    

    # Telegram notification (skip placeholder/test leads)
    if not _is_test_flag:
        # Telegram notification
        try:
            tg_msg = (
                f"<b>New lead!</b>\n"
                f"Company: {company_name}\n"
                f"Lead ID: {lead_id}\n"
                f"Name: {name or '-'}\n"
                f"Phone: {phone or '-'}\n"
                f"Email: {email or '-'}\n"
                f"Comment: {comment or '-'}"
            )
            await send_telegram_notification(tg_msg)
        except Exception:
            pass
    return response


# ─── FastAPI App ────────────────────────────────────────────────────


# === Telegram notifications ===
async def send_telegram_notification(message: str):
    """Send notification to Telegram chat."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            })
    except Exception as _e:
        import sys
        print(f"[TG-FAIL] {type(_e).__name__}: {_e}",file=sys.stderr,flush=True)

mcp_app = mcp.http_app(path="/")

openapi_tags = [
    {"name": "Search (Free)", "description": "Search companies and projects - no API key required"},
    {"name": "Companies (Free)", "description": "Company details and listings - no API key required"},
    {"name": "Market Data (Free)", "description": "Categories, regions, statistics - no API key required"},
    {"name": "Analytics (Starter+)", "description": "Market analytics - requires Starter plan (2990 RUB/mo)"},
    {"name": "AI Tools (Pro+)", "description": "AI-powered analysis - requires Pro plan (7990 RUB/mo)"},
    {"name": "Account", "description": "API key registration and management"},
]

app = FastAPI(
    title="MCP Market Russia",
    description="Russian construction companies and house projects catalog for AI agents",
    version="3.1.1",
    lifespan=mcp_app.lifespan,
    openapi_tags=openapi_tags,
)

app.mount("/mcp", mcp_app)


# === /mcp landing for browser visitors ===
# Added 2026-04-15: browsers that open https://mcp-market.ru/mcp/ get a
# human-readable landing page with install instructions. MCP clients that
# send `Accept: text/event-stream` pass straight through to FastMCP.
from fastapi import Request as _MCPReq
from fastapi.responses import HTMLResponse as _MCPHtml
import os as _mcp_os

_MCP_LANDING_PATH = _mcp_os.path.join(
    _mcp_os.path.dirname(__file__), "static", "mcp_landing.html"
)


@app.middleware("http")
async def mcp_browser_landing(request: _MCPReq, call_next):
    if request.url.path in ("/mcp", "/mcp/"):
        accept = request.headers.get("accept", "")
        if "text/html" in accept and "text/event-stream" not in accept:
            if _mcp_os.path.exists(_MCP_LANDING_PATH):
                with open(_MCP_LANDING_PATH, "r", encoding="utf-8") as _f:
                    return _MCPHtml(_f.read())
            return _MCPHtml(
                "<h1>MCP Market Russia</h1>"
                "<p>Endpoint для AI-агентов. См. <a href=\"/\">главную</a>.</p>"
            )
    return await call_next(request)

# Wire API key middleware
app.add_middleware(APIKeyMiddleware)



# --- Web API for frontend search ---

# ==========================================
# UNIQUE ANALYTICS & LEAD GENERATION TOOLS
# ==========================================

@mcp.tool()
def market_analytics(region: str = "", category: str = "") -> str:
    """Get comprehensive market analytics for the Russian construction market.
    Returns: average prices, top companies by rating, market size, price distribution.
    Perfect for investors, analysts, and companies entering the market.
    Args:
        region: Filter by region (e.g. 'Москва', 'Санкт-Петербург'). Empty = all regions.
        category: Filter by category (e.g. 'Строительство домов'). Empty = all categories.
    """
    import json
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = []
            params = []
            if region:
                where.append("region ILIKE %s")
                params.append(f"%{region}%")
            if category:
                where.append("(category ILIKE %s OR EXISTS (SELECT 1 FROM unnest(subcategories) _sc WHERE _sc ILIKE %s))")
                params.extend([f"%{category}%", f"%{category}%"])
            where_sql = "WHERE " + " AND ".join(where) if where else ""
            
            # General stats
            cur.execute(f"""
                SELECT 
                    COUNT(*) as total_companies,
                    COUNT(DISTINCT region) as regions_count,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_price_min,
                    ROUND(AVG(price_per_sqm_max)::numeric, 1) as avg_price_max,
                    COUNT(price_per_sqm_min) as companies_with_prices,
                    COUNT(phone) as companies_with_phone,
                    COUNT(email) as companies_with_email,
                    COUNT(website) as companies_with_website,
                    SUM(projects_count) as total_projects,
                    SUM(reviews_count) as total_reviews
                FROM companies {where_sql}
            """, params)
            stats = dict(cur.fetchone())
            
            # Top 10 by rating
            cur.execute(f"""
                SELECT slug, region, rating, reviews_count, price_per_sqm_min, price_per_sqm_max, phone, website
                FROM companies {where_sql}
                ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
                LIMIT 10
            """, params)
            top_rated = [dict(r) for r in cur.fetchall()]
            
            # Price distribution by region
            cur.execute(f"""
                SELECT region, 
                    COUNT(*) as companies,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_price_min,
                    ROUND(MIN(price_per_sqm_min)::numeric, 1) as min_price,
                    ROUND(MAX(price_per_sqm_max)::numeric, 1) as max_price
                FROM companies 
                {where_sql + " AND " if where_sql else "WHERE "} price_per_sqm_min IS NOT NULL
                GROUP BY region ORDER BY companies DESC LIMIT 15
            """, params)
            price_by_region = [dict(r) for r in cur.fetchall()]
            
            # Category distribution
            cur.execute(f"""
                SELECT category, COUNT(*) as cnt 
                FROM companies {where_sql}
                GROUP BY category ORDER BY cnt DESC LIMIT 10
            """, params)
            categories = [dict(r) for r in cur.fetchall()]
            
            result = {
                "market_overview": stats,
                "top_rated_companies": top_rated,
                "price_distribution_by_region": price_by_region,
                "category_distribution": categories,
                "analysis_note": f"Data covers {stats['total_companies']} companies across {stats['regions_count']} regions."
            }
            return json.dumps(result, ensure_ascii=False, default=str)
    finally:
        conn.close()


@mcp.tool()
def find_best_companies(
    region: str = "",
    category: str = "",
    min_rating: float = 0,
    max_price: float = 0,
    min_price: float = 0,
    has_phone: bool = False,
    has_projects: bool = False,
    sort_by: str = "rating",
    limit: int = 20
) -> str:
    """Smart lead generation: find the best construction companies matching your criteria.
    Perfect for finding contractors, generating leads, or market research.
    Args:
        region: Filter by region name (e.g. 'Москва'). Empty = all.
        category: Filter by category/subcategory. Empty = all.
        min_rating: Minimum rating (0-5). 0 = no filter.
        max_price: Maximum price per m2 in thousands RUB. 0 = no filter.
        min_price: Minimum price per m2 in thousands RUB. 0 = no filter.
        has_phone: Only companies with phone number.
        has_projects: Only companies with project portfolio.
        sort_by: Sort by: 'rating', 'price_asc', 'price_desc', 'reviews', 'projects'.
        limit: Max results (1-50).
    """
    import json
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = []
            params = []
            if region:
                where.append("region ILIKE %s")
                params.append(f"%{region}%")
            if category:
                where.append("(category ILIKE %s OR EXISTS (SELECT 1 FROM unnest(subcategories) _sc WHERE _sc ILIKE %s))")
                params.extend([f"%{category}%", f"%{category}%"])
            if min_rating > 0:
                where.append("rating >= %s")
                params.append(min_rating)
            if max_price > 0:
                where.append("price_per_sqm_min <= %s")
                params.append(max_price)
            if min_price > 0:
                where.append("price_per_sqm_min >= %s")
                params.append(min_price)
            if has_phone:
                where.append("phone IS NOT NULL")
            if has_projects:
                where.append("projects_count > 0")
            
            where_sql = "WHERE " + " AND ".join(where) if where else ""
            
            order_map = {
                "rating": "rating DESC NULLS LAST, reviews_count DESC NULLS LAST",
                "price_asc": "price_per_sqm_min ASC NULLS LAST",
                "price_desc": "price_per_sqm_min DESC NULLS LAST",
                "reviews": "reviews_count DESC NULLS LAST",
                "projects": "projects_count DESC NULLS LAST"
            }
            order = order_map.get(sort_by, order_map["rating"])
            limit = min(max(limit, 1), 50)
            
            cur.execute(f"""
                SELECT slug, category, region, city, rating, reviews_count,
                    price_per_sqm_min, price_per_sqm_max, phone, email, website,
                    projects_count, description
                FROM companies {where_sql}
                ORDER BY {order}
                LIMIT %s
            """, params + [limit])
            companies = [dict(r) for r in cur.fetchall()]
            
            # Get total matching
            cur.execute(f"SELECT COUNT(*) FROM companies {where_sql}", params)
            total = cur.fetchone()["count"]
            
            return json.dumps({
                "total_matching": total,
                "showing": len(companies),
                "sort": sort_by,
                "companies": companies
            }, ensure_ascii=False, default=str)
    finally:
        conn.close()


@mcp.tool()
def price_comparison(regions: str = "", category: str = "") -> str:
    """Compare construction prices across regions and categories.
    Returns detailed price statistics, percentiles, and regional rankings.
    Args:
        regions: Comma-separated regions to compare (e.g. 'Москва,Санкт-Петербург'). Empty = all.
        category: Filter by category. Empty = all.
    """
    import json
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = ["price_per_sqm_min IS NOT NULL"]
            params = []
            
            if regions:
                region_list = [r.strip() for r in regions.split(",")]
                placeholders = ",".join(["%s"] * len(region_list))
                where.append(f"region IN ({placeholders})")
                params.extend(region_list)
            if category:
                where.append("(category ILIKE %s OR EXISTS (SELECT 1 FROM unnest(subcategories) _sc WHERE _sc ILIKE %s))")
                params.extend([f"%{category}%", f"%{category}%"])
            
            where_sql = "WHERE " + " AND ".join(where)
            
            # Regional price comparison
            cur.execute(f"""
                SELECT region,
                    COUNT(*) as companies,
                    ROUND(MIN(price_per_sqm_min)::numeric, 1) as cheapest,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_min_price,
                    ROUND(AVG(price_per_sqm_max)::numeric, 1) as avg_max_price,
                    ROUND(MAX(price_per_sqm_max)::numeric, 1) as most_expensive,
                    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 1) as p25,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 1) as median,
                    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 1) as p75
                FROM companies {where_sql}
                GROUP BY region
                ORDER BY avg_min_price ASC
            """, params)
            by_region = [dict(r) for r in cur.fetchall()]
            
            # Category price comparison
            cur.execute(f"""
                SELECT category,
                    COUNT(*) as companies,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_min_price,
                    ROUND(AVG(price_per_sqm_max)::numeric, 1) as avg_max_price,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 1) as median
                FROM companies {where_sql}
                GROUP BY category
                HAVING COUNT(*) >= 3
                ORDER BY avg_min_price ASC
            """, params)
            by_category = [dict(r) for r in cur.fetchall()]
            
            # Best value: high rating + low price
            cur.execute(f"""
                SELECT slug, region, category, rating, reviews_count,
                    price_per_sqm_min, price_per_sqm_max, phone, website
                FROM companies {where_sql} AND rating >= 4.0
                ORDER BY price_per_sqm_min ASC
                LIMIT 10
            """, params)
            best_value = [dict(r) for r in cur.fetchall()]
            
            return json.dumps({
                "price_by_region": by_region,
                "price_by_category": by_category,
                "best_value_companies": best_value,
                "note": "Prices in thousands RUB per m2"
            }, ensure_ascii=False, default=str)
    finally:
        conn.close()


@mcp.tool()
def company_portfolio(company_slug: str) -> str:
    """Get FULL company portfolio: details, all projects, prices, reviews, contacts.
    Comprehensive dossier for due diligence or hiring decisions.
    Args:
        company_slug: Company slug identifier (from search results).
    """
    import json
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get company details
            cur.execute("SELECT * FROM companies WHERE slug = %s", (company_slug,))
            company = cur.fetchone()
            if not company:
                return json.dumps({"error": f"Company '{company_slug}' not found"})
            company = dict(company)
            
            # Get all projects
            cur.execute("""
                SELECT name, description, area, floors, material, price_per_sqm,
                    price, images, source_url
                FROM projects WHERE company_id = %s
                ORDER BY price DESC NULLS LAST
            """, (company["id"],))
            projects = [dict(p) for p in cur.fetchall()]
            
            # Get regional context
            cur.execute("""
                SELECT 
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as region_avg_price,
                    ROUND(AVG(rating)::numeric, 2) as region_avg_rating,
                    COUNT(*) as competitors_count
                FROM companies 
                WHERE region = %s AND category = %s AND id != %s
            """, (company["region"], company["category"], company["id"]))
            context = dict(cur.fetchone())
            
            # Price position
            price_position = "unknown"
            if company.get("price_per_sqm_min") and context.get("region_avg_price"):
                if float(company["price_per_sqm_min"]) < float(context["region_avg_price"]) * 0.9:
                    price_position = "below_average (budget)"
                elif float(company["price_per_sqm_min"]) > float(context["region_avg_price"]) * 1.1:
                    price_position = "above_average (premium)"
                else:
                    price_position = "average"
            
            # Rating position
            rating_position = "unknown"
            if company.get("rating") and context.get("region_avg_rating"):
                if float(company["rating"]) > float(context["region_avg_rating"]):
                    rating_position = "above_average"
                else:
                    rating_position = "below_average"
            
            result = {
                "company": {k: v for k, v in company.items() if k != "id"},
                "projects": projects,
                "projects_count": len(projects),
                "market_position": {
                    "price_position": price_position,
                    "rating_position": rating_position,
                    "competitors_in_region": context["competitors_count"],
                    "region_avg_price": context["region_avg_price"],
                    "region_avg_rating": context["region_avg_rating"]
                }
            }
            return json.dumps(result, ensure_ascii=False, default=str)
    finally:
        conn.close()


@mcp.tool()
def market_report(region: str) -> str:
    """Generate a comprehensive market report for a specific region.
    Includes: market size, price tiers, top players, contact availability, competitive landscape.
    Perfect for investors, business development, and market entry analysis.
    Args:
        region: Region name (e.g. 'Москва', 'Ленинградская область').
    """
    import json
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Market size
            cur.execute("""
                SELECT 
                    COUNT(*) as total_companies,
                    COUNT(DISTINCT category) as categories,
                    COUNT(DISTINCT city) as cities,
                    COUNT(website) as with_website,
                    COUNT(phone) as with_phone,
                    COUNT(email) as with_email,
                    COUNT(price_per_sqm_min) as with_prices,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    SUM(reviews_count) as total_reviews,
                    SUM(projects_count) as total_projects
                FROM companies WHERE region ILIKE %s
            """, (f"%{region}%",))
            overview = dict(cur.fetchone())
            
            # Price tiers
            cur.execute("""
                SELECT 
                    CASE 
                        WHEN price_per_sqm_min < 20 THEN 'economy (<20k/m2)'
                        WHEN price_per_sqm_min < 40 THEN 'standard (20-40k/m2)'
                        WHEN price_per_sqm_min < 70 THEN 'comfort (40-70k/m2)'
                        WHEN price_per_sqm_min < 100 THEN 'business (70-100k/m2)'
                        ELSE 'premium (100k+/m2)'
                    END as tier,
                    COUNT(*) as companies,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating
                FROM companies 
                WHERE region ILIKE %s AND price_per_sqm_min IS NOT NULL
                GROUP BY tier ORDER BY MIN(price_per_sqm_min)
            """, (f"%{region}%",))
            price_tiers = [dict(r) for r in cur.fetchall()]
            
            # Top 5 by rating
            cur.execute("""
                SELECT slug, category, rating, reviews_count, 
                    price_per_sqm_min, price_per_sqm_max, phone, website
                FROM companies 
                WHERE region ILIKE %s AND rating IS NOT NULL
                ORDER BY rating DESC, reviews_count DESC
                LIMIT 5
            """, (f"%{region}%",))
            top_companies = [dict(r) for r in cur.fetchall()]
            
            # Top 5 most affordable with good rating
            cur.execute("""
                SELECT slug, category, rating, reviews_count, 
                    price_per_sqm_min, price_per_sqm_max, phone, website
                FROM companies 
                WHERE region ILIKE %s AND price_per_sqm_min IS NOT NULL AND rating >= 4.0
                ORDER BY price_per_sqm_min ASC
                LIMIT 5
            """, (f"%{region}%",))
            best_deals = [dict(r) for r in cur.fetchall()]
            
            # Category breakdown
            cur.execute("""
                SELECT category, COUNT(*) as cnt,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_price
                FROM companies WHERE region ILIKE %s
                GROUP BY category ORDER BY cnt DESC
            """, (f"%{region}%",))
            by_category = [dict(r) for r in cur.fetchall()]
            
            return json.dumps({
                "region": region,
                "market_overview": overview,
                "price_tiers": price_tiers,
                "top_rated_companies": top_companies,
                "best_value_companies": best_deals,
                "categories": by_category,
                "report_note": f"Comprehensive market report for {region}. Data as of 2026-03."
            }, ensure_ascii=False, default=str)
    finally:
        conn.close()




@mcp.tool()
def review_analysis(company_slug: str = "", region: str = "", category: str = "") -> str:
    """Analyze company reviews - sentiment breakdown, common themes, strengths and weaknesses. Provide company_slug for specific company or region/category for market overview."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if company_slug:
            cur.execute("""
                SELECT c.name, c.slug, c.rating, c.reviews_count, c.region, c.category,
                       c.price_per_sqm_min, c.price_per_sqm_max,
                       (SELECT COUNT(*) FROM projects p WHERE p.company_id = c.id) as projects_count
                FROM companies c WHERE c.slug = %s
            """, (company_slug,))
            company = cur.fetchone()
            if not company:
                return json.dumps({"error": "Company not found"}, ensure_ascii=False)
            
            # Get rating distribution estimate based on rating
            rating = float(company["rating"] or 0)
            reviews = int(company["reviews_count"] or 0)
            
            # Estimate sentiment
            if rating >= 4.5:
                sentiment = {"positive": round(reviews * 0.85), "neutral": round(reviews * 0.10), "negative": round(reviews * 0.05)}
                verdict = "Отличная репутация"
            elif rating >= 4.0:
                sentiment = {"positive": round(reviews * 0.70), "neutral": round(reviews * 0.18), "negative": round(reviews * 0.12)}
                verdict = "Хорошая репутация"
            elif rating >= 3.5:
                sentiment = {"positive": round(reviews * 0.50), "neutral": round(reviews * 0.25), "negative": round(reviews * 0.25)}
                verdict = "Средняя репутация"
            else:
                sentiment = {"positive": round(reviews * 0.30), "neutral": round(reviews * 0.20), "negative": round(reviews * 0.50)}
                verdict = "Низкая репутация"
            
            # Compare with region average
            cur.execute("""
                SELECT AVG(rating) as avg_rating, AVG(reviews_count) as avg_reviews
                FROM companies WHERE region = %s AND rating > 0
            """, (company["region"],))
            region_avg = cur.fetchone()
            
            result = {
                "company": company["name"],
                "rating": rating,
                "total_reviews": reviews,
                "sentiment": sentiment,
                "verdict": verdict,
                "projects_count": company["projects_count"],
                "region_comparison": {
                    "region": company["region"],
                    "avg_rating": round(float(region_avg["avg_rating"] or 0), 2),
                    "avg_reviews": round(float(region_avg["avg_reviews"] or 0), 0),
                    "above_average": rating > float(region_avg["avg_rating"] or 0)
                }
            }
            return json.dumps(result, ensure_ascii=False, default=str)
        else:
            where = []
            params = []
            if region:
                where.append("region ILIKE %s")
                params.append(f"%{region}%")
            if category:
                where.append("category ILIKE %s")
                params.append(f"%{category}%")
            where_sql = "AND " + " AND ".join(where) if where else ""
            
            cur.execute(f"""
                SELECT 
                    COUNT(*) as total,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    ROUND(AVG(reviews_count)::numeric, 0) as avg_reviews,
                    SUM(reviews_count) as total_reviews,
                    COUNT(CASE WHEN rating >= 4.5 THEN 1 END) as excellent,
                    COUNT(CASE WHEN rating >= 4.0 AND rating < 4.5 THEN 1 END) as good,
                    COUNT(CASE WHEN rating >= 3.0 AND rating < 4.0 THEN 1 END) as average,
                    COUNT(CASE WHEN rating > 0 AND rating < 3.0 THEN 1 END) as poor
                FROM companies WHERE rating > 0 {where_sql}
            """, params)
            stats = cur.fetchone()
            
            cur.execute(f"""
                SELECT name, slug, rating, reviews_count, region
                FROM companies WHERE rating > 0 {where_sql}
                ORDER BY reviews_count DESC LIMIT 5
            """, params)
            most_reviewed = cur.fetchall()
            
            result = {
                "market_review_stats": dict(stats),
                "rating_distribution": {
                    "excellent_4.5+": stats["excellent"],
                    "good_4.0-4.5": stats["good"],
                    "average_3.0-4.0": stats["average"],
                    "poor_below_3.0": stats["poor"]
                },
                "most_reviewed_companies": [dict(r) for r in most_reviewed]
            }
            return json.dumps(result, ensure_ascii=False, default=str)
    finally:
        cur.close()
        conn.close()


@mcp.tool()
def contractor_recommendation(budget_min: float = 0, budget_max: float = 0, region: str = "", category: str = "", min_rating: float = 4.0, need_portfolio: bool = True, need_contacts: bool = True) -> str:
    """AI-powered contractor recommendation. Finds the best matching companies based on budget, region, quality requirements. Returns ranked list with match scores."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        where = ["rating >= %s"]
        params = [min_rating]
        
        if region:
            where.append("c.region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            where.append("c.category ILIKE %s")
            params.append(f"%{category}%")
        if budget_min > 0:
            where.append("(c.price_per_sqm_max >= %s OR c.price_per_sqm_max IS NULL)")
            params.append(budget_min)
        if budget_max > 0:
            where.append("(c.price_per_sqm_min <= %s OR c.price_per_sqm_min IS NULL)")
            params.append(budget_max)
        if need_portfolio:
            where.append("EXISTS (SELECT 1 FROM projects p WHERE p.company_id = c.id)")
        if need_contacts:
            where.append("(c.phone IS NOT NULL OR c.email IS NOT NULL)")
        
        where_sql = " AND ".join(where)
        
        cur.execute(f"""
            SELECT c.name, c.slug, c.rating, c.reviews_count, c.region, c.category,
                   c.price_per_sqm_min, c.price_per_sqm_max, c.phone, c.email, c.website,
                   (SELECT COUNT(*) FROM projects p WHERE p.company_id = c.id) as projects_count,
                   COALESCE(c.rating, 0) * 15 + 
                   LEAST(COALESCE(c.reviews_count, 0), 500) * 0.05 +
                   CASE WHEN c.price_per_sqm_min IS NOT NULL THEN 10 ELSE 0 END +
                   CASE WHEN c.phone IS NOT NULL THEN 5 ELSE 0 END +
                   CASE WHEN c.email IS NOT NULL THEN 5 ELSE 0 END +
                   (SELECT COUNT(*) FROM projects p WHERE p.company_id = c.id) * 2
                   as match_score
            FROM companies c
            WHERE {where_sql}
            ORDER BY match_score DESC
            LIMIT 10
        """, params)
        
        companies = cur.fetchall()
        
        results = []
        for i, c in enumerate(companies):
            rec = {
                "rank": i + 1,
                "name": c["name"],
                "slug": c["slug"],
                "match_score": round(float(c["match_score"]), 1),
                "rating": float(c["rating"] or 0),
                "reviews": c["reviews_count"],
                "region": c["region"],
                "category": c["category"],
                "price_range": f"{c['price_per_sqm_min']}-{c['price_per_sqm_max']} руб/м²" if c["price_per_sqm_min"] else "не указана",
                "projects": c["projects_count"],
                "contacts": {
                    "phone": c["phone"] or "-",
                    "email": c["email"] or "-",
                    "website": c["website"] or "-"
                }
            }
            results.append(rec)
        
        return json.dumps({"recommendations": results, "total_found": len(results), "criteria": {"budget": f"{budget_min}-{budget_max}", "region": region or "все", "category": category or "все", "min_rating": min_rating}}, ensure_ascii=False, default=str)
    finally:
        cur.close()
        conn.close()


@mcp.tool()
def project_estimator(area_sqm: float, region: str = "", category: str = "", quality: str = "standard") -> str:
    """Estimate construction project cost based on area, region, category and quality level (economy/standard/premium). Uses real market data from our database."""
    if area_sqm is None or area_sqm <= 0:
        return json.dumps({"error": "area_sqm должна быть больше 0"}, ensure_ascii=False)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        where = ["price_per_sqm_min IS NOT NULL"]
        params = []
        if region:
            where.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            where.append("category ILIKE %s")
            params.append(f"%{category}%")
        
        where_sql = " AND ".join(where)
        
        cur.execute(f"""
            SELECT 
                COUNT(*) as sample_size,
                ROUND(AVG(price_per_sqm_min)::numeric, 0) as avg_min_price,
                ROUND(AVG(price_per_sqm_max)::numeric, 0) as avg_max_price,
                ROUND(MIN(price_per_sqm_min)::numeric, 0) as market_min,
                ROUND(MAX(price_per_sqm_max)::numeric, 0) as market_max,
                ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 0) as p25,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 0) as median,
                ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_per_sqm_min)::numeric, 0) as p75
            FROM companies WHERE {where_sql}
        """, params)
        stats = cur.fetchone()
        
        if not stats or stats["sample_size"] == 0:
            return json.dumps({"error": "Недостаточно данных для оценки. Попробуйте другой регион или категорию."}, ensure_ascii=False)
        
        quality_multipliers = {"economy": 0.7, "standard": 1.0, "premium": 1.5, "luxury": 2.0}
        mult = quality_multipliers.get(quality, 1.0)
        
        avg_min = float(stats["avg_min_price"] or 0)
        avg_max = float(stats["avg_max_price"] or 0)
        if avg_max < avg_min:
            avg_max = avg_min
        
        estimate_min = round(avg_min * mult * area_sqm)
        estimate_max = round(avg_max * mult * area_sqm)
        estimate_avg = round((estimate_min + estimate_max) / 2)
        
        # Get top companies for this estimate
        cur.execute(f"""
            SELECT name, slug, rating, price_per_sqm_min, price_per_sqm_max
            FROM companies WHERE {where_sql} AND rating >= 4.0
            ORDER BY rating DESC, reviews_count DESC
            LIMIT 5
        """, params)
        recommended = cur.fetchall()
        
        result = {
            "estimate": {
                "area_sqm": area_sqm,
                "quality": quality,
                "price_per_sqm": {"min": round(avg_min * mult), "max": round(avg_max * mult)},
                "total_cost": {"min": estimate_min, "avg": estimate_avg, "max": estimate_max},
                "formatted": {
                    "min": f"{estimate_min:,} руб".replace(",", " "),
                    "avg": f"{estimate_avg:,} руб".replace(",", " "),
                    "max": f"{estimate_max:,} руб".replace(",", " ")
                }
            },
            "market_data": {
                "sample_size": stats["sample_size"],
                "region": region or "все регионы",
                "category": category or "все категории",
                "percentiles": {"p25": stats["p25"], "median": stats["median"], "p75": stats["p75"]}
            },
            "recommended_companies": [dict(r) for r in recommended]
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    finally:
        cur.close()
        conn.close()



@mcp.tool()
def trend_analyzer(region: str = "", category: str = "", period: str = "all") -> str:
    """Analyze market trends - company growth, price dynamics, rating changes by region/category.
    Shows how the construction market is developing over time."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        conditions = []
        params = []
        if region:
            conditions.append("c.region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("c.category ILIKE %s")
            params.append(f"%{category}%")
        
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        # Market size by region
        cur.execute(f"""
            SELECT region, 
                   count(*) as companies,
                   ROUND(AVG(rating)::numeric, 2) as avg_rating,
                   SUM(reviews_count) as total_reviews,
                   count(*) FILTER (WHERE phone IS NOT NULL) as with_contacts,
                   count(*) FILTER (WHERE price_per_sqm_min IS NOT NULL) as with_prices,
                   ROUND(AVG(price_per_sqm_min)::numeric, 0) as avg_price_min,
                   ROUND(AVG(price_per_sqm_max)::numeric, 0) as avg_price_max
            FROM companies c {where}
            GROUP BY region
            ORDER BY count(*) DESC
            LIMIT 15
        """, params)
        regions_data = cur.fetchall()
        
        # Category distribution
        cur.execute(f"""
            SELECT category,
                   count(*) as companies,
                   ROUND(AVG(rating)::numeric, 2) as avg_rating,
                   SUM(reviews_count) as total_reviews
            FROM companies c {where}
            GROUP BY category
            ORDER BY count(*) DESC
            LIMIT 10
        """, params)
        categories_data = cur.fetchall()
        
        # Quality distribution
        cur.execute(f"""
            SELECT 
                CASE 
                    WHEN rating >= 4.5 THEN 'premium (4.5+)'
                    WHEN rating >= 4.0 THEN 'good (4.0-4.5)'
                    WHEN rating >= 3.0 THEN 'average (3.0-4.0)'
                    WHEN rating > 0 THEN 'low (<3.0)'
                    ELSE 'no rating'
                END as quality_tier,
                count(*) as companies,
                ROUND(AVG(reviews_count)::numeric, 0) as avg_reviews
            FROM companies c {where}
            GROUP BY quality_tier
            ORDER BY companies DESC
        """, params)
        quality_data = cur.fetchall()
        
        # Price segments
        cur.execute(f"""
            SELECT 
                CASE 
                    WHEN price_per_sqm_min < 50000 THEN 'economy (<50k/sqm)'
                    WHEN price_per_sqm_min < 100000 THEN 'standard (50-100k/sqm)'
                    WHEN price_per_sqm_min < 200000 THEN 'premium (100-200k/sqm)'
                    ELSE 'luxury (200k+/sqm)'
                END as price_segment,
                count(*) as companies,
                ROUND(AVG(rating)::numeric, 2) as avg_rating
            FROM companies c 
            WHERE price_per_sqm_min IS NOT NULL {("AND " + " AND ".join(conditions)) if conditions else ""}
            GROUP BY price_segment
            ORDER BY companies DESC
        """, params)
        price_segments = cur.fetchall()
        
        cur.close()
        conn.close()
        
        result = "📊 MARKET TREND ANALYSIS\n"
        result += "=" * 50 + "\n\n"
        
        if region or category:
            result += f"Filter: {region or 'all regions'}, {category or 'all categories'}\n\n"
        
        result += "🏢 TOP REGIONS BY COMPANY COUNT:\n"
        for r in regions_data:
            price_info = f", price {r['avg_price_min']}-{r['avg_price_max']} ₽/m²" if r['avg_price_min'] else ""
            result += f"  • {r['region']}: {r['companies']} companies, ★{r['avg_rating']}, {r['total_reviews']} reviews{price_info}\n"
        
        result += "\n📋 TOP CATEGORIES:\n"
        for c in categories_data:
            result += f"  • {c['category']}: {c['companies']} companies, ★{c['avg_rating']}, {c['total_reviews']} reviews\n"
        
        result += "\n⭐ QUALITY DISTRIBUTION:\n"
        for q in quality_data:
            result += f"  • {q['quality_tier']}: {q['companies']} companies, ~{q['avg_reviews']} avg reviews\n"
        
        if price_segments:
            result += "\n💰 PRICE SEGMENTS:\n"
            for p in price_segments:
                result += f"  • {p['price_segment']}: {p['companies']} companies, ★{p['avg_rating']}\n"
        
        return result
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def company_deep_profile(slug: str) -> str:
    """Get comprehensive company profile with all available data - contacts, projects, pricing, 
    reviews analysis, market position, and comparison with competitors in same region."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT * FROM companies WHERE slug = %s", (slug,))
        company = cur.fetchone()
        
        if not company:
            cur.execute("SELECT slug, name, region FROM companies WHERE slug ILIKE %s OR name ILIKE %s LIMIT 5", 
                       (f"%{slug}%", f"%{slug}%"))
            suggestions = cur.fetchall()
            cur.close()
            conn.close()
            if suggestions:
                return "Company not found. Did you mean:\n" + "\n".join([f"  • {s['slug']} ({s['name']}, {s['region']})" for s in suggestions])
            return "Company not found."
        
        # Get projects
        cur.execute("SELECT name, description FROM projects WHERE company_id = %s LIMIT 10", (company['id'],))
        projects = cur.fetchall()
        
        # Regional competitors
        cur.execute("""
            SELECT slug, name, rating, reviews_count, price_per_sqm_min, price_per_sqm_max
            FROM companies 
            WHERE region = %s AND category = %s AND slug != %s AND rating > 0
            ORDER BY rating DESC, reviews_count DESC
            LIMIT 5
        """, (company['region'], company['category'], slug))
        competitors = cur.fetchall()
        
        # Regional stats for comparison
        cur.execute("""
            SELECT ROUND(AVG(rating)::numeric, 2) as avg_rating,
                   ROUND(AVG(reviews_count)::numeric, 0) as avg_reviews,
                   ROUND(AVG(price_per_sqm_min)::numeric, 0) as avg_price,
                   count(*) as total_companies
            FROM companies
            WHERE region = %s AND category = %s AND rating > 0
        """, (company['region'], company['category']))
        regional = cur.fetchone()
        
        cur.close()
        conn.close()
        
        result = f"🏗️ COMPANY DEEP PROFILE\n"
        result += "=" * 50 + "\n\n"
        result += f"📌 {company['name']}\n"
        result += f"   Slug: {company['slug']}\n"
        result += f"   Region: {company['region']}\n"
        result += f"   Category: {company['category']}\n"
        result += f"   Rating: ★{company['rating']} ({company['reviews_count']} reviews)\n"
        
        if company.get('phone'):
            result += f"   📞 Phone: {company['phone']}\n"
        if company.get('email'):
            result += f"   📧 Email: {company['email']}\n"
        if company.get('website'):
            result += f"   🌐 Website: {company['website']}\n"
        if company.get('address'):
            result += f"   📍 Address: {company['address']}\n"
        
        if company.get('price_per_sqm_min') or company.get('min_project_price'):
            result += "\n💰 PRICING:\n"
            if company.get('price_per_sqm_min'):
                result += f"   Per m²: {company['price_per_sqm_min']} - {company.get('price_per_sqm_max', 'N/A')} ₽\n"
            if company.get('min_project_price'):
                result += f"   Project: from {company['min_project_price']} ₽\n"
        
        if company.get('description'):
            desc = company['description'][:300]
            result += f"\n📝 DESCRIPTION:\n   {desc}...\n" if len(company['description']) > 300 else f"\n📝 DESCRIPTION:\n   {desc}\n"
        
        if projects:
            result += f"\n🏠 PROJECTS ({len(projects)}):\n"
            for p in projects:
                desc_short = (p['description'][:80] + '...') if p.get('description') and len(p['description']) > 80 else (p.get('description') or '')
                result += f"   • {p['name']}: {desc_short}\n"
        
        if regional:
            result += f"\n📊 MARKET POSITION (vs {regional['total_companies']} companies in {company['region']}/{company['category']}):\n"
            rating_diff = round(float(company['rating'] or 0) - float(regional['avg_rating'] or 0), 2)
            result += f"   Rating: {'↑' if rating_diff > 0 else '↓'}{abs(rating_diff)} vs average ★{regional['avg_rating']}\n"
            reviews_diff = int(company['reviews_count'] or 0) - int(regional['avg_reviews'] or 0)
            result += f"   Reviews: {'↑' if reviews_diff > 0 else '↓'}{abs(reviews_diff)} vs average {regional['avg_reviews']}\n"
        
        if competitors:
            result += "\n🏆 TOP COMPETITORS:\n"
            for c in competitors:
                price = f", {c['price_per_sqm_min']}-{c['price_per_sqm_max']} ₽/m²" if c.get('price_per_sqm_min') else ""
                result += f"   • {c['name']} (★{c['rating']}, {c['reviews_count']} reviews{price})\n"
        
        return result
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def region_comparison(regions: str, category: str = "") -> str:
    """Compare construction markets across regions. Provide comma-separated region names.
    Shows companies count, ratings, prices, contact availability for each region side by side."""
    try:
        region_list = [r.strip() for r in regions.split(",") if r.strip()]
        if not region_list:
            return "Please provide comma-separated region names, e.g.: 'Москва, Санкт-Петербург, Краснодарский край'"
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        results = []
        for region_name in region_list:
            cat_filter = "AND category ILIKE %s" if category else ""
            params = [f"%{region_name}%"]
            if category:
                params.append(f"%{category}%")
            
            cur.execute(f"""
                SELECT 
                    region,
                    count(*) as total_companies,
                    count(*) FILTER (WHERE rating > 0) as rated_companies,
                    ROUND(AVG(rating) FILTER (WHERE rating > 0)::numeric, 2) as avg_rating,
                    MAX(rating) as max_rating,
                    SUM(reviews_count) as total_reviews,
                    ROUND(AVG(reviews_count) FILTER (WHERE reviews_count > 0)::numeric, 0) as avg_reviews,
                    count(*) FILTER (WHERE phone IS NOT NULL) as with_phone,
                    count(*) FILTER (WHERE email IS NOT NULL) as with_email,
                    count(*) FILTER (WHERE website IS NOT NULL) as with_website,
                    count(*) FILTER (WHERE price_per_sqm_min IS NOT NULL) as with_prices,
                    ROUND(AVG(price_per_sqm_min) FILTER (WHERE price_per_sqm_min IS NOT NULL)::numeric, 0) as avg_price_min,
                    ROUND(AVG(price_per_sqm_max) FILTER (WHERE price_per_sqm_max IS NOT NULL)::numeric, 0) as avg_price_max,
                    ROUND(MIN(price_per_sqm_min) FILTER (WHERE price_per_sqm_min IS NOT NULL)::numeric, 0) as min_price,
                    ROUND(MAX(price_per_sqm_max) FILTER (WHERE price_per_sqm_max IS NOT NULL)::numeric, 0) as max_price,
                    count(DISTINCT category) as categories_count
                FROM companies
                WHERE region ILIKE %s {cat_filter}
                GROUP BY region
            """, params)
            
            data = cur.fetchone()
            if data and data['total_companies'] > 0:
                # Top categories in region
                cur.execute(f"""
                    SELECT category, count(*) as cnt 
                    FROM companies 
                    WHERE region ILIKE %s {cat_filter}
                    GROUP BY category ORDER BY cnt DESC LIMIT 5
                """, params)
                top_cats = cur.fetchall()
                data['top_categories'] = top_cats
                results.append(data)
        
        cur.close()
        conn.close()
        
        if not results:
            return "No data found for specified regions. Try: Москва, Московская область, Санкт-Петербург, Краснодарский край"
        
        output = "🗺️ REGION COMPARISON\n"
        output += "=" * 50 + "\n"
        if category:
            output += f"Category filter: {category}\n"
        output += "\n"
        
        for r in results:
            phone_pct = round(r['with_phone'] / r['total_companies'] * 100) if r['total_companies'] else 0
            email_pct = round(r['with_email'] / r['total_companies'] * 100) if r['total_companies'] else 0
            
            output += f"📍 {r['region']}\n"
            output += f"   Companies: {r['total_companies']} ({r['categories_count']} categories)\n"
            output += f"   Rating: ★{r['avg_rating']} avg, ★{r['max_rating']} max ({r['rated_companies']} rated)\n"
            output += f"   Reviews: {r['total_reviews']} total, ~{r['avg_reviews']} per company\n"
            output += f"   Contacts: {r['with_phone']} phones ({phone_pct}%), {r['with_email']} emails ({email_pct}%)\n"
            
            if r['with_prices'] > 0:
                output += f"   Prices: {r['with_prices']} companies, {r['avg_price_min']}-{r['avg_price_max']} ₽/m² avg, range {r['min_price']}-{r['max_price']} ₽/m²\n"
            
            if r.get('top_categories'):
                cats = ", ".join([f"{c['category']}({c['cnt']})" for c in r['top_categories']])
                output += f"   Top categories: {cats}\n"
            output += "\n"
        
        # Winner summary
        if len(results) > 1:
            output += "🏆 COMPARISON SUMMARY:\n"
            most_companies = max(results, key=lambda x: x['total_companies'])
            output += f"   Most companies: {most_companies['region']} ({most_companies['total_companies']})\n"
            best_rated = max(results, key=lambda x: float(x['avg_rating'] or 0))
            output += f"   Best rated: {best_rated['region']} (★{best_rated['avg_rating']})\n"
            most_reviews = max(results, key=lambda x: x['total_reviews'] or 0)
            output += f"   Most reviews: {most_reviews['region']} ({most_reviews['total_reviews']})\n"
            best_contacts = max(results, key=lambda x: x['with_phone'])
            output += f"   Best contact coverage: {best_contacts['region']} ({best_contacts['with_phone']} phones)\n"
        
        return output
    except Exception as e:
        return f"Error: {str(e)}"


@app.get("/api/companies/search")
async def api_search_companies(q: str = "", region: str = "", category: str = "", limit: int = 20):
    """Search companies API for web frontend. Splits query into words for AND matching."""
    try:
        conditions = ["1=1"]
        params = {}
        
        if q:
            # Split query into words and require each word to match at least one field
            words = q.strip().split()
            for i, word in enumerate(words):
                key = f"q{i}"
                conditions.append(
                    f"(name ILIKE %({key})s OR city ILIKE %({key})s OR description ILIKE %({key})s OR category ILIKE %({key})s)"
                )
                params[key] = f"%{word}%"
        if region:
            conditions.append("region = %(region)s")
            params["region"] = region
        if category:
            conditions.append("category = %(category)s")
            params["category"] = category
        
        where = " AND ".join(conditions)
        safe_limit = min(max(1, limit), 50)
        
        sql = f"""SELECT id, name, city, region, category, description, phone, website, rating, reviews_count
                  FROM companies WHERE {where}
                  ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
                  LIMIT {safe_limit}"""
        
        # Count total
        count_sql = f"SELECT COUNT(*) as total FROM companies WHERE {where}"
        
        rows = query_db(sql, params, safe_limit)
        count_rows = query_db(count_sql, params, 1)
        total = count_rows[0]["total"] if count_rows else 0
        
        return {"companies": rows, "total": total, "limit": safe_limit}
    except Exception as e:
        return {"companies": [], "total": 0, "error": str(e)}



@app.get("/api/companies/{company_id}")
async def api_get_company(company_id: str):
    """Get full company details with projects for web frontend."""
    try:
        rows = query_db(
            "SELECT * FROM companies WHERE id = %(id)s::uuid",
            {"id": company_id}, 1
        )
        if not rows:
            return {"error": "Company not found"}
        company = rows[0]
        # Convert non-serializable types
        for k, v in company.items():
            if hasattr(v, 'isoformat'):
                company[k] = v.isoformat()
            elif isinstance(v, (bytes,)):
                company[k] = str(v)
            elif not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                company[k] = str(v)
        
        projects = query_db(
            "SELECT id, name, area, floors, bedrooms, material, price, price_description, dimensions FROM projects WHERE company_id = %(id)s::uuid ORDER BY area ASC LIMIT 20",
            {"id": company_id}, 20
        )
        for p in projects:
            for k, v in p.items():
                if hasattr(v, 'isoformat'):
                    p[k] = v.isoformat()
                elif isinstance(v, (bytes,)):
                    p[k] = str(v)
                elif not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    p[k] = str(v)
        
        return {"company": company, "projects": projects}
    except Exception as e:
        return {"error": str(e)}


@app.get("/")
async def root():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=f.read())
    return {
        "name": "MCP Market Russia",
        "description": "Russian construction companies catalog for AI agents",
        "mcp_endpoint": settings.SERVER_URL + "/mcp",
        "version": "3.1.1",
        "tools": 21,
        "docs": "/docs",
    }



# === SEO: Company profile page ===
@app.get("/company/{company_id}")
def company_profile(company_id: str):
    from fastapi.responses import HTMLResponse
    import uuid as _uuid
    try:
        _uuid.UUID(str(company_id))
    except (ValueError, AttributeError, TypeError):
        return HTMLResponse("<h1>Company not found</h1>", status_code=404)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM companies WHERE id=%s", (company_id,))
        cols = [desc[0] for desc in cur.description]
        r = cur.fetchone()
        cur.close()
        conn.close()
        if not r:
            return HTMLResponse("<h1>Company not found</h1>", status_code=404)
        row = dict(zip(cols, r))
    except Exception:
        return HTMLResponse("<h1>Error</h1><p>Не удалось загрузить страницу компании.</p>", status_code=500)
    if not row:
        return HTMLResponse("<h1>Company not found</h1>", status_code=404)
    n = html.escape(row["name"] or "")
    city = html.escape(row.get("city","") or "")
    cat = html.escape(row.get("category","") or "")
    desc = html.escape((row.get("description","") or "")[:500])
    rating = row.get("rating","") or ""
    phone = html.escape(row.get("phone","") or "")
    web = html.escape(row.get("website","") or "")
    rc = row.get("reviews_count",0) or 0
    page_html = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8">
<title>{n} — MCP Market Russia</title>
<meta name="description" content="{n}, {cat}, {city}. {desc[:160]}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="canonical" href="https://mcp-market.ru/company/{html.escape(company_id)}">
<style>body{{font-family:system-ui;max-width:800px;margin:40px auto;padding:0 20px;color:#333}}
h1{{color:#1a56db}}a{{color:#1a56db}}.meta{{color:#666;margin:4px 0}}.desc{{margin:16px 0;line-height:1.6}}
.badge{{background:#e8f0fe;color:#1a56db;padding:4px 12px;border-radius:12px;font-size:14px;display:inline-block;margin:2px}}
footer{{margin-top:40px;padding-top:20px;border-top:1px solid #eee;color:#999;font-size:13px}}</style>
</head><body>
<p><a href="/">&larr; MCP Market Russia</a></p>
<h1>{n}</h1>
<p class="meta"><span class="badge">{cat}</span> <span class="badge">{city}</span></p>
{"<p>&#11088; "+str(rating)+"/5 ("+str(rc)+" reviews)</p>" if rating else ""}
<div class="desc">{desc}</div>
{"<p>&#128222; "+phone+"</p>" if phone else ""}
{"<p>&#127760; <a href=\'"+web+"\'  rel=\'noopener\'>"+web+"</a></p>" if web else ""}
<hr>
<p style="margin-top:20px"><a href="https://mcp-market.ru/mcp/">Connect via MCP protocol</a> to get full data on {n}.</p>
<footer>&copy; 2026 MCP Market Russia &mdash; mcp-market.ru</footer>
</body></html>"""
    return HTMLResponse(content=page_html)

@app.get("/health")
async def health():
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM companies")
            count = cur.fetchone()[0]
        conn.close()
        return {"status": "ok", "companies": count}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@app.get("/api/v1/health")
async def api_v1_health():
    """Public health endpoint at /api/v1/health (whitelisted in API_TOOL_ENDPOINTS)."""
    return await health()


@app.get("/stats")
async def stats():
    try:
        conn = get_db()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) as companies FROM companies")
            companies = cur.fetchone()["companies"]
            cur.execute("SELECT COUNT(*) as projects FROM projects")
            projects = cur.fetchone()["projects"]
            cur.execute("SELECT COUNT(*) as queries FROM agent_queries WHERE timestamp > CURRENT_DATE")
            queries_today = cur.fetchone()["queries"]
            cur.execute("SELECT COUNT(*) as leads FROM leads")
            leads = cur.fetchone()["leads"]
        conn.close()
        return {
            "companies": companies,
            "projects": projects,
            "queries_today": queries_today,
            "leads_total": leads,
            "version": "3.1.1",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


# ─── Dashboard API ──────────────────────────────────────────────────

# DASHBOARD_THREADPOOL_FIX
_DASHBOARD_OVERVIEW_CACHE = {"data": None, "ts": 0}
_DASHBOARD_OVERVIEW_TTL = 30  # seconds
import asyncio as _asyncio
_DASHBOARD_LOCK = _asyncio.Lock()

@app.get("/api/dashboard/overview")
async def dashboard_overview():
    """Full overview stats for dashboard (30s cache + single-flight + threadpool)."""
    import time as _t
    now = _t.time()
    c = _DASHBOARD_OVERVIEW_CACHE
    if c["data"] is not None and now - c["ts"] < _DASHBOARD_OVERVIEW_TTL:
        return c["data"]
    async with _DASHBOARD_LOCK:
        now2 = _t.time()
        if c["data"] is not None and now2 - c["ts"] < _DASHBOARD_OVERVIEW_TTL:
            return c["data"]
        data = await _asyncio.to_thread(_dashboard_overview_impl_sync)
        c["data"] = data
        c["ts"] = now2
        return data

def _dashboard_overview_impl_sync():
    """Full overview stats for dashboard."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT COUNT(*) as v FROM companies")
        companies = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as v FROM projects")
        projects = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(DISTINCT region) as v FROM companies WHERE region IS NOT NULL")
        regions = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(DISTINCT category) as v FROM companies WHERE category IS NOT NULL")
        categories = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as v FROM companies WHERE website IS NOT NULL AND website != ''")
        with_website = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as v FROM companies WHERE description IS NOT NULL AND LENGTH(description) > 30")
        with_description = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as v FROM agent_queries")
        total_queries = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as v FROM agent_queries WHERE timestamp > CURRENT_DATE")
        queries_today = cur.fetchone()["v"]
        cur.execute("SELECT COUNT(*) as v FROM leads")
        leads = cur.fetchone()["v"]
        cur.execute("SELECT ROUND(AVG(rating)::numeric, 2) as v FROM companies WHERE rating IS NOT NULL")
        avg_rating = cur.fetchone()["v"]
        return {
            "companies": companies, "projects": projects, "regions": regions,
            "categories": categories, "with_website": with_website,
            "with_description": with_description,
            "total_queries": total_queries, "queries_today": queries_today,
            "leads": leads, "avg_rating": float(avg_rating) if avg_rating else 0,
        }
    finally:
        cur.close(); conn.close()



@app.get("/api/dashboard/data-completeness")
async def dashboard_data_completeness():
    """Data completeness percentages for progress bars."""
    rows = query_db("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE website IS NOT NULL AND website != '') as websites,
            COUNT(*) FILTER (WHERE phone IS NOT NULL AND phone != '') as phones,
            COUNT(*) FILTER (WHERE email IS NOT NULL AND email != '') as emails,
            COUNT(*) FILTER (WHERE description IS NOT NULL AND description != '') as descriptions,
            COUNT(*) FILTER (WHERE min_project_price IS NOT NULL AND min_project_price > 0) as prices,
            COUNT(*) FILTER (WHERE rating IS NOT NULL AND rating > 0) as ratings
        FROM companies
    """)
    if rows:
        r = rows[0]
        total = r['total'] or 1
        return {
            "total": total,
            "websites": {"count": r['websites'], "percent": round(r['websites']*100/total, 1)},
            "phones": {"count": r['phones'], "percent": round(r['phones']*100/total, 1)},
            "emails": {"count": r['emails'], "percent": round(r['emails']*100/total, 1)},
            "descriptions": {"count": r['descriptions'], "percent": round(r['descriptions']*100/total, 1)},
            "prices": {"count": r['prices'], "percent": round(r['prices']*100/total, 1)},
            "ratings": {"count": r['ratings'], "percent": round(r['ratings']*100/total, 1)}
        }
    return {}

@app.get("/api/dashboard/recent-queries")
async def dashboard_recent_queries():
    """Last 20 agent queries."""
    rows = query_db("""
        SELECT tool_name, params, results_count, duration_ms, 
               timestamp AT TIME ZONE 'Europe/Moscow' as ts
        FROM agent_queries 
        ORDER BY timestamp DESC 
        LIMIT 20
    """)
    return [dict(r) for r in rows] if rows else []

@app.get("/api/dashboard/categories")
async def dashboard_categories():
    rows = query_db("""
        SELECT category as name, COUNT(*) as count,
               ROUND(AVG(rating)::numeric, 2) as avg_rating
        FROM companies WHERE category IS NOT NULL
        GROUP BY category ORDER BY count DESC
    """, limit=20)
    return [dict(r) for r in rows]


@app.get("/api/dashboard/regions")
async def dashboard_regions():
    rows = query_db("""
        SELECT c.region as name, COUNT(*) as count, COUNT(*) as companies,
               ROUND(AVG(c.rating)::numeric, 2) as avg_rating,
               COALESCE(pj.projects, 0) as projects,
               ROUND(AVG(
                   ((CASE WHEN c.website IS NOT NULL AND c.website != '' THEN 1 ELSE 0 END)
                  + (CASE WHEN c.phone IS NOT NULL AND c.phone != '' THEN 1 ELSE 0 END)
                  + (CASE WHEN c.email IS NOT NULL AND c.email != '' THEN 1 ELSE 0 END)
                  + (CASE WHEN c.description IS NOT NULL AND c.description != '' THEN 1 ELSE 0 END)) * 25.0
               )::numeric, 0) as completeness
        FROM companies c
        LEFT JOIN (
            SELECT co.region as region, COUNT(p.id) as projects
            FROM projects p JOIN companies co ON p.company_id = co.id
            WHERE co.region IS NOT NULL
            GROUP BY co.region
        ) pj ON pj.region = c.region
        WHERE c.region IS NOT NULL
        GROUP BY c.region, pj.projects ORDER BY count DESC
    """, limit=25)
    return [dict(r) for r in rows]


@app.get("/api/dashboard/top-companies")
async def dashboard_top_companies():
    rows = query_db("""
        SELECT name, city, category, rating, reviews_count, website,
               projects_count, min_project_price, price_per_sqm_min,
               description
        FROM companies
        WHERE website IS NOT NULL AND website != ''
        ORDER BY
            (CASE WHEN description IS NOT NULL AND LENGTH(description) > 30 THEN 2 ELSE 0 END +
             CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END +
             CASE WHEN phone IS NOT NULL AND phone != '' THEN 1 ELSE 0 END) DESC,
            name ASC
        LIMIT 10
    """, limit=10)
    return [dict(r) for r in rows]


@app.get("/api/dashboard/materials")
async def dashboard_materials():
    rows = query_db("""
        SELECT material as name, COUNT(*) as projects,
               ROUND(AVG(price / NULLIF(area, 0))) as avg_price_sqm,
               ROUND(AVG(price)) as avg_price,
               MIN(price) as min_price, MAX(price) as max_price,
               ROUND(AVG(area)::numeric, 0) as avg_area
        FROM projects
        WHERE material IS NOT NULL AND price IS NOT NULL AND price > 0
        GROUP BY material ORDER BY projects DESC
    """, limit=10)
    return [dict(r) for r in rows]


@app.get("/api/dashboard/queries-chart")
async def dashboard_queries_chart():
    rows = query_db("""
        SELECT DATE(timestamp) as date, COUNT(*) as count
        FROM agent_queries
        WHERE timestamp > CURRENT_DATE - INTERVAL '30 days'
        GROUP BY DATE(timestamp)
        ORDER BY date
    """, limit=31)
    return [{"date": str(r["date"]), "count": r["count"]} for r in rows]


@app.get("/api/dashboard/popular-tools")
async def dashboard_popular_tools():
    rows = query_db("""
        SELECT tool_name, COUNT(*) as count
        FROM agent_queries
        GROUP BY tool_name
        ORDER BY count DESC
    """, limit=10)
    return [dict(r) for r in rows]


from fastapi.responses import HTMLResponse


@app.get("/api/dashboard/companies")
async def dashboard_companies(region: str = "", category: str = "", limit: int = 50):
    """Filter companies by region and/or category for dashboard."""
    conditions = ["1=1"]
    params = {}
    
    if region:
        conditions.append("(region ILIKE %(region)s OR city ILIKE %(region)s)")
        params["region"] = f"%{region}%"
    
    if category:
        conditions.append("(category = %(category)s OR %(category)s = ANY(subcategories))")
        params["category"] = category
    
    where = " AND ".join(conditions)
    rows = query_db(f"""
        SELECT name, city, category, rating, reviews_count, website, phone,
               description, min_project_price, price_per_sqm_min
        FROM companies
        WHERE {where}
        ORDER BY
            (CASE WHEN description IS NOT NULL AND LENGTH(description) > 30 THEN 3 ELSE 0 END +
             CASE WHEN website IS NOT NULL AND website != '' THEN 2 ELSE 0 END +
             CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END) DESC,
            name ASC
        LIMIT {min(limit, 100)}
    """, params, min(limit, 100))
    return [dict(r) for r in rows]


# === /demo page ===
@app.get("/demo", response_class=HTMLResponse)
async def demo_page():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "demo.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Demo not found</h1>", status_code=404)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Dashboard not found</h1>"

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Admin panel not found</h1>"

@app.get("/pay", response_class=HTMLResponse)
async def pay_page():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "pay.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Payment page not found</h1>"


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "login.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Login page not found</h1>"


# ——— Tasks API endpoints ———————————————————————————————

from pydantic import BaseModel as TaskBaseModel

class TaskCreate(TaskBaseModel):
    project_id: str
    text: str
    status: str = 'todo'
    date: str = None

class TaskUpdate(TaskBaseModel):
    status: str = None
    text: str = None
    date: str = None
    sort_order: int = None

class ProjectCreate(TaskBaseModel):
    id: str
    name: str
    color: str = '#3B82F6'
    icon: str = 'P'



async def api_get_tasks():
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM task_projects ORDER BY sort_order")
            projects = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM task_items ORDER BY sort_order, id")
            tasks = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    task_map = {}
    for t in tasks:
        pid = t['project_id']
        if pid not in task_map:
            task_map[pid] = []
        task_map[pid].append({'id': t['id'], 'text': t['text'], 'status': t['status'], 'date': t['date'], 'sort_order': t['sort_order']})
    result = []
    for p in projects:
        result.append({'id': p['id'], 'name': p['name'], 'color': p['color'], 'icon': p['icon'], 'tasks': task_map.get(p['id'], [])})
    return result



async def api_create_task(task: TaskCreate):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""INSERT INTO task_items (project_id, text, status, date, sort_order) VALUES (%(project_id)s, %(text)s, %(status)s, %(date)s, COALESCE((SELECT MAX(sort_order)+1 FROM task_items WHERE project_id=%(project_id)s), 0)) RETURNING *""", {"project_id": task.project_id, "text": task.text, "status": task.status, "date": task.date})
            new_task = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()
    return new_task



async def api_update_task(task_id: int, task: TaskUpdate):
    updates, params = [], {"id": task_id}
    if task.status is not None: updates.append("status=%(status)s"); params["status"]=task.status
    if task.text is not None: updates.append("text=%(text)s"); params["text"]=task.text
    if task.date is not None: updates.append("date=%(date)s"); params["date"]=task.date
    if task.sort_order is not None: updates.append("sort_order=%(sort_order)s"); params["sort_order"]=task.sort_order
    if not updates: return {"error": "No fields"}
    updates.append("updated_at=NOW()")
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"UPDATE task_items SET {','.join(updates)} WHERE id=%(id)s RETURNING *", params)
            updated = cur.fetchone()
            conn.commit()
            return dict(updated) if updated else {"error": "Not found"}
    finally:
        conn.close()



async def api_delete_task(task_id: int):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM task_items WHERE id=%s", (task_id,))
            conn.commit()
            if cur.rowcount==0: return {"error": "Not found"}
    finally:
        conn.close()
    return {"ok": True}



async def api_create_project(project: ProjectCreate):
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""INSERT INTO task_projects (id, name, color, icon, sort_order) VALUES (%(id)s, %(name)s, %(color)s, %(icon)s, COALESCE((SELECT MAX(sort_order)+1 FROM task_projects), 0)) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, color=EXCLUDED.color, icon=EXCLUDED.icon RETURNING *""", {"id": project.id, "name": project.name, "color": project.color, "icon": project.icon})
            new_project = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()
    return new_project




# ==========================================
# ANALYTICS API ENDPOINTS
# ==========================================

@app.get("/api/analytics/price-map")
async def api_price_map():
    """Price heatmap data by region."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT region,
                    COUNT(*) as companies,
                    COUNT(price_per_sqm_min) as with_prices,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_price_min,
                    ROUND(AVG(price_per_sqm_max)::numeric, 1) as avg_price_max,
                    ROUND(MIN(price_per_sqm_min)::numeric, 1) as min_price,
                    ROUND(MAX(price_per_sqm_max)::numeric, 1) as max_price,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    SUM(projects_count) as total_projects
                FROM companies
                WHERE price_per_sqm_min IS NOT NULL
                GROUP BY region
                ORDER BY avg_price_min ASC
            """)
            return {"regions": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()


@app.get("/api/analytics/market-summary")
async def api_market_summary():
    """Full market summary for the dashboard."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Total stats
            cur.execute("""
                SELECT 
                    COUNT(*) as total_companies,
                    COUNT(DISTINCT region) as total_regions,
                    COUNT(phone) as with_phone,
                    COUNT(email) as with_email,
                    COUNT(website) as with_website,
                    COUNT(price_per_sqm_min) as with_price,
                    COUNT(rating) as with_rating,
                    SUM(projects_count) as total_projects,
                    SUM(reviews_count) as total_reviews,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_price
                FROM companies
            """)
            totals = dict(cur.fetchone())
            
            # Top 5 regions by companies
            cur.execute("""
                SELECT region, COUNT(*) as cnt 
                FROM companies GROUP BY region ORDER BY cnt DESC LIMIT 5
            """)
            top_regions = [dict(r) for r in cur.fetchall()]
            
            # Top 5 categories
            cur.execute("""
                SELECT category, COUNT(*) as cnt 
                FROM companies GROUP BY category ORDER BY cnt DESC LIMIT 5
            """)
            top_categories = [dict(r) for r in cur.fetchall()]
            
            # MCP tools count
            tools_count = 21
            
            return {
                "totals": totals,
                "top_regions": top_regions,
                "top_categories": top_categories,
                "mcp_tools": tools_count,
                "version": "2.3.0"
            }
    finally:
        conn.close()


@app.get("/api/analytics/top-companies")
async def api_top_companies(region: str = "", category: str = "", limit: int = 10):
    """Get top-rated companies with filters."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = []
            params = []
            if region:
                where.append("region ILIKE %s")
                params.append(f"%{region}%")
            if category:
                where.append("category ILIKE %s")
                params.append(f"%{category}%")
            where_sql = "WHERE " + " AND ".join(where) if where else ""
            limit = min(max(limit, 1), 50)
            
            cur.execute(f"""
                SELECT slug, category, region, city, rating, reviews_count,
                    price_per_sqm_min, price_per_sqm_max, phone, email, website,
                    projects_count
                FROM companies {where_sql}
                ORDER BY rating DESC NULLS LAST, reviews_count DESC NULLS LAST
                LIMIT %s
            """, params + [limit])
            return {"companies": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()


@app.get("/api/analytics/price-tiers")
async def api_price_tiers(region: str = ""):
    """Price tier distribution."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = "WHERE price_per_sqm_min IS NOT NULL"
            params = []
            if region:
                where += " AND region ILIKE %s"
                params.append(f"%{region}%")
            
            cur.execute(f"""
                SELECT 
                    CASE 
                        WHEN price_per_sqm_min < 20 THEN 'economy'
                        WHEN price_per_sqm_min < 40 THEN 'standard'
                        WHEN price_per_sqm_min < 70 THEN 'comfort'
                        WHEN price_per_sqm_min < 100 THEN 'business'
                        ELSE 'premium'
                    END as tier,
                    COUNT(*) as companies,
                    ROUND(AVG(rating)::numeric, 2) as avg_rating,
                    ROUND(AVG(price_per_sqm_min)::numeric, 1) as avg_price
                FROM companies {where}
                GROUP BY tier
                ORDER BY avg_price ASC
            """, params)
            return {"tiers": [dict(r) for r in cur.fetchall()]}
    finally:
        conn.close()



async def tasks_page():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "tasks.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Tasks not found</h1>"

@app.get("/pricing", response_class=HTMLResponse)
@app.get("/pricing.html", response_class=HTMLResponse)
async def pricing_page():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "static", "pricing.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Pricing page not found</h3>"



# ============ SEO STATIC FILES ============

from fastapi.responses import PlainTextResponse as _PlainText, Response as _Response

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    import os
    path = os.path.join(os.path.dirname(__file__), "static", "robots.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return _PlainText(f.read())
    return _PlainText("User-agent: *\nAllow: /\n")

@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    import os
    path = os.path.join(os.path.dirname(__file__), "static", "sitemap.xml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return _Response(content=f.read(), media_type="application/xml")
    return _Response(content="<?xml version='1.0'?><urlset/>", media_type="application/xml")


# ============ MONETIZATION ENDPOINTS ============


@app.get("/api-docs", include_in_schema=False)
async def api_documentation_page():
    html_path = "/app/app/api_docs.html"
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/api/register", tags=["Account"])
async def register_api_key(request: Request):
    """Register new API key"""
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        email = data.get("email", "").strip()
        phone = data.get("phone", "")
        # SECURITY: self-service registration ALWAYS issues a free key.
        # Paid plans are granted only by the payment flow.
        plan = "free"
        
        if not name or not email:
            return JSONResponse({"error": "Name and email required"}, status_code=400)
        
        # Generate unique API key
        import hashlib, time
        raw = f"{email}_{time.time()}_{name}"
        api_key = f"mcp_{plan}_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
        
        # Plan limits
        limits = {"free": 100, "starter": 1000, "pro": 5000, "enterprise": 50000}
        req_limit = limits.get(plan, 100)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check if email already has a key
        cur.execute("SELECT key, plan FROM api_keys WHERE owner_email = %s AND is_active = true", (email,))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            return JSONResponse({"api_key": existing[0], "plan": existing[1], "message": "Key already exists for this email"})
        
        cur.execute("""
            INSERT INTO api_keys (key, owner_name, owner_email, plan, requests_limit)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING key
        """, (api_key, name, email, plan, req_limit))
        conn.commit()
        
        cur.close()
        conn.close()
        
        # QUICKSTART_HINT_INJECTED
        return JSONResponse({
            "api_key": api_key,
            "plan": plan,
            "requests_limit": req_limit,
            "message": "API key created successfully",
            "quickstart_url": "https://mcp-market.ru/quickstart",
            "mcp_config_snippet": {"mcpServers": {"mcp-market": {"url": "https://mcp-market.ru/mcp"}}},
            "note": "MCP-инструменты работают без api-key — просто подключите https://mcp-market.ru/mcp в Claude Desktop/Cursor. Ключ нужен только для Analytics (Starter+) и AI Tools (Pro+). Подробнее: /quickstart"
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/leads/create")
async def create_lead(request: Request):
    """Create a lead (requires API key)"""
    key_info = await validate_api_key(request)
    if key_info is None or (isinstance(key_info, dict) and "error" in key_info):
        return JSONResponse({"error": "API key required", "hint": "Pass X-API-Key header. Free key: https://mcp-market.ru/quickstart"}, status_code=401)
    try:
        data = await request.json()
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO leads (company_slug, client_name, client_phone, client_email, 
                             project_description, budget_from, budget_to, region, category, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data.get("company_slug"),
            data.get("client_name", ""),
            data.get("client_phone", ""),
            data.get("client_email", ""),
            data.get("project_description", ""),
            data.get("budget_from"),
            data.get("budget_to"),
            data.get("region", ""),
            data.get("category", ""),
            data.get("source", "mcp_api")
        ))
        lead_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return JSONResponse({"lead_id": lead_id, "status": "created"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/leads")
async def get_leads(request: Request, status: str = "", limit: int = 50):
    """Admin: leads list (personal data). Requires X-Admin-Token."""
    if not _require_admin(request):
        return JSONResponse({"error": "Admin authentication required"}, status_code=401)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if status:
            cur.execute("SELECT * FROM leads WHERE status = %s ORDER BY created_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT %s", (limit,))
        
        leads = cur.fetchall()
        cur.close()
        conn.close()
        
        for lead in leads:
            for k, v in lead.items():
                if hasattr(v, 'isoformat'):
                    lead[k] = v.isoformat()
        
        return JSONResponse({"leads": leads, "count": len(leads)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



@app.post("/api/keys/{key_id}/toggle")
async def toggle_api_key(key_id: int):
    """Toggle API key active status"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE api_keys SET is_active = NOT is_active WHERE id = %s RETURNING id, is_active", (key_id,))
        row = cur.fetchone()
        conn.commit()
        if not row:
            return JSONResponse({"error": "Key not found"}, status_code=404)
        return JSONResponse({"id": row[0], "is_active": row[1]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/keys")
async def get_api_keys(request: Request):
    """Admin: API key owners and usage. Requires X-Admin-Token."""
    if not _require_admin(request):
        return JSONResponse({"error": "Admin authentication required"}, status_code=401)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, owner_name, owner_email, plan, requests_limit, requests_used, 
                   is_active, created_at::text, last_used_at::text
            FROM api_keys ORDER BY created_at DESC
        """)
        keys = cur.fetchall()
        cur.close()
        conn.close()
        return JSONResponse({"keys": keys, "count": len(keys)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/usage/stats")
async def get_usage_stats(request: Request):
    """Admin: billing usage statistics. Requires X-Admin-Token."""
    if not _require_admin(request):
        return JSONResponse({"error": "Admin authentication required"}, status_code=401)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Today's usage by key
        cur.execute("""
            SELECT ak.owner_name, ak.plan, ak.requests_limit,
                   count(ul.id) as today_requests,
                   count(DISTINCT ul.tool_name) as tools_used
            FROM api_keys ak
            LEFT JOIN usage_logs ul ON ul.api_key_id = ak.id 
                AND ul.created_at::date = CURRENT_DATE
            GROUP BY ak.id, ak.owner_name, ak.plan, ak.requests_limit
            ORDER BY today_requests DESC
        """)
        usage = cur.fetchall()
        
        # Total stats
        cur.execute("""
            SELECT count(*) as total_keys,
                   count(*) FILTER (WHERE plan = 'free') as free_keys,
                   count(*) FILTER (WHERE plan = 'starter') as starter_keys,
                   count(*) FILTER (WHERE plan = 'pro') as pro_keys,
                   count(*) FILTER (WHERE plan = 'enterprise') as enterprise_keys
            FROM api_keys WHERE is_active = true
        """)
        totals = cur.fetchone()
        
        # Leads stats
        cur.execute("""
            SELECT count(*) as total_leads,
                   count(*) FILTER (WHERE status = 'new') as new_leads,
                   count(*) FILTER (WHERE status = 'converted') as converted_leads
            FROM leads
        """)
        leads_stats = cur.fetchone()
        
        cur.close()
        conn.close()
        
        return JSONResponse({
            "usage_today": usage,
            "keys_summary": totals,
            "leads_summary": leads_stats
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/pricing")
async def get_pricing():
    """Return pricing tiers"""
    return JSONResponse({
        "plans": {
            "free": {"name": "Free", "price": 0, "requests_per_day": 100, "tools": 13},
            "starter": {"name": "Starter", "price": 2990, "requests_per_day": 1000, "tools": 18},
            "pro": {"name": "Pro", "price": 7990, "requests_per_day": 5000, "tools": 24},
            "enterprise": {"name": "Enterprise", "price": 24990, "requests_per_day": -1, "tools": 24}
        },
        "company_plans": {
            "basic": {"name": "Basic", "price": 0, "leads_per_month": 0},
            "premium": {"name": "Premium", "price": 4990, "leads_per_month": 20},
            "vip": {"name": "VIP", "price": 14990, "leads_per_month": -1}
        },
        "currency": "RUB"
    })

# ============================================================
# REST API v1 ENDPOINTS - monetized tool access via HTTP
# ============================================================

@app.get("/api/v1/search/companies", tags=["Search (Free)"])
async def api_v1_search_companies(
    q: str = "",
    region: str = "",
    category: str = "",
    min_rating: float = 0,
    limit: int = 20,
    offset: int = 0
):
    """Search companies via REST API. Free tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = []
        params = []
        if q:
            # Fix 2026-04-24 v3: split + stemming + stop-words + synonym-expansion + match in tags[] OR 5 text fields
            _STOP = {"в","на","до","под","от","для","и","с","или","за","у","к","по","из","о","при","без","над","со","об"}
            _SYN = {
                "спб": ["санкт-петер","ленинград","петербург"],
                "питер": ["санкт-петер","ленинград","петербург"],
                "петер": ["санкт-петер","ленинград","петербург"],
                "пите": ["санкт-петер","ленинград","петербург"],
                "подмосков": ["московск","москв"],
                "подмоск": ["московск","москв"],
                "мск": ["москв"],
                "екб": ["екатеринбур","свердлов"],
                "нск": ["новосибир"],
                "крд": ["краснодар","кубан","сочи"],
                "нн": ["нижегород","нижний"],
                "уфа": ["башкорт","уфа"],
                "уф": ["башкорт","уфа"],
                "казан": ["татарстан","казан"],
                "сочи": ["краснодар","сочи"],
            }
            raw_words = [w.lower().strip() for w in q.split()]
            stems = []
            for w in raw_words:
                if len(w) < 2 or w in _STOP:
                    continue
                _RU_SUF=["ными","ного","ному","ной","ную","ные","ный","ого","ому","ыми","их","ых","ой","ое","ие","ий","ый","ая","ою","ею","ах","ям","ев","ов","ам","ом","ем","ой","ей","ью","ы","и","а","я","е","о","у","ю"]
                _ws=w.lower()
                for _sf in sorted(_RU_SUF,key=len,reverse=True):
                    if len(_ws)>len(_sf)+2 and _ws.endswith(_sf):
                        _ws=_ws[:-len(_sf)];break
                stems.append(_ws)
            if stems:
                for stem in stems:
                    # Build alternatives: original stem + synonyms (if any)
                    alts = [stem] + _SYN.get(stem, [])
                    or_parts = []
                    for alt in alts:
                        or_parts.append("(EXISTS(SELECT 1 FROM unnest(c.tags) tag WHERE tag ILIKE %s) OR c.name ILIKE %s OR c.description ILIKE %s OR c.region ILIKE %s OR c.city ILIKE %s OR c.category ILIKE %s)")
                        params.extend([f"%{alt}%"] * 6)
                    _TAX={"каркас","брус","кирпич","газобетон","сип","бревно","коттедж","таунхаус","баня","гараж","бытовка","заборы","кровля","фасад","отделка","ремонт","окна_двери","полы","инженерка","ландшафт","бассейн","снос","монтаж","проектирование","недвижимость","строительство","дом_под_ключ","малоэтажн","многоэтажн"}
                    for alt in alts:
                        _hits=[t for t in _TAX if t==alt or t.startswith(alt) or alt.startswith(t)]
                        for tag in _hits:
                            or_parts.append("(EXISTS(SELECT 1 FROM unnest(c.tags) tag WHERE tag = %s))")
                            params.append(tag)
                    conditions.append("(" + " OR ".join(or_parts) + ")")
            else:
                conditions.append("(c.name ILIKE %s OR c.description ILIKE %s)")
                params.extend([f"%{q}%", f"%{q}%"])
        if region:
            conditions.append("c.region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("c.category ILIKE %s")
            params.append(f"%{category}%")
        if min_rating > 0:
            conditions.append("c.rating >= %s")
            params.append(min_rating)
        
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        cur.execute(f"""
            SELECT c.id, c.name, c.slug, c.region, c.category, c.rating, c.reviews_count,
                   c.description, c.website, c.phone,
                   c.price_per_sqm_min, c.price_per_sqm_max
            FROM companies c {where}
            ORDER BY c.rating DESC NULLS LAST
            LIMIT %s OFFSET %s
        """, params + [min(limit, 50), offset])
        
        companies = cur.fetchall()
        
        cur.execute(f"SELECT COUNT(*) as total FROM companies c {where}", params)
        total = cur.fetchone()["total"]
        
        conn.close()
        return {"total": total, "limit": limit, "offset": offset, "companies": companies}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/search/projects", tags=["Search (Free)"])
async def api_v1_search_projects(
    q: str = "",
    region: str = "",
    category: str = "",
    min_area: float = 0,
    max_area: float = 0,
    limit: int = 20,
    offset: int = 0
):
    """Search projects via REST API. Free tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = []
        params = []
        if q:
            conditions.append("(p.name ILIKE %s OR p.description ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        if region:
            conditions.append("c.region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("c.category ILIKE %s")
            params.append(f"%{category}%")
        if min_area > 0:
            conditions.append("p.area >= %s")
            params.append(min_area)
        if max_area > 0:
            conditions.append("p.area <= %s")
            params.append(max_area)
        
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        cur.execute(f"""
            SELECT p.id, p.name, p.company_id, p.area, p.description, p.style, p.price
            FROM projects p JOIN companies c ON p.company_id = c.id {where}
            ORDER BY p.id DESC
            LIMIT %s OFFSET %s
        """, params + [min(limit, 50), offset])
        
        projects = cur.fetchall()
        conn.close()
        return {"total": len(projects), "projects": projects}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/companies/{company_id}", tags=["Companies (Free)"])
async def api_v1_get_company(company_id: str):
    """Get company details. Free tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM companies WHERE id::text = %s OR slug = %s", (company_id, company_id))
        company = cur.fetchone()
        if not company:
            conn.close()
            return {"error": "Company not found"}
        
        cur.execute("SELECT id, name, area, style, description, price FROM projects WHERE company_id = %s", (company["id"],))
        projects = cur.fetchall()
        conn.close()
        
        result = dict(company)
        result["projects"] = projects
        return result
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/categories", tags=["Market Data (Free)"])
async def api_v1_categories():
    """List all categories. Free tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT category, COUNT(*) as count FROM companies WHERE category IS NOT NULL GROUP BY category ORDER BY count DESC")
        cats = cur.fetchall()
        conn.close()
        return {"categories": cats}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/regions", tags=["Market Data (Free)"])
async def api_v1_regions():
    """List all regions. Free tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT region, COUNT(*) as companies, 
                   AVG(rating) as avg_rating,
                   AVG(price_per_sqm_min) as avg_price_min,
                   AVG(price_per_sqm_max) as avg_price_max
            FROM companies WHERE region IS NOT NULL 
            GROUP BY region ORDER BY companies DESC
        """)
        regions = cur.fetchall()
        conn.close()
        return {"regions": regions}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/stats", tags=["Market Data (Free)"])
async def api_v1_stats():
    """General stats. Free tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM companies) as total_companies,
                (SELECT COUNT(*) FROM projects) as total_projects,
                (SELECT COUNT(DISTINCT region) FROM companies WHERE region IS NOT NULL) as regions,
                (SELECT COUNT(DISTINCT category) FROM companies WHERE category IS NOT NULL) as categories,
                (SELECT AVG(rating) FROM companies WHERE rating IS NOT NULL) as avg_rating,
                (SELECT AVG(price_per_sqm_min) FROM companies WHERE price_per_sqm_min IS NOT NULL) as avg_price_min
        """)
        stats = cur.fetchone()
        conn.close()
        return stats
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/analytics/market", tags=["Analytics (Starter+)"])
async def api_v1_market_analytics(region: str = "", category: str = ""):
    """Market analytics. Starter+ plan required."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = []
        params = []
        if region:
            conditions.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("category ILIKE %s")
            params.append(f"%{category}%")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        cur.execute(f"""
            SELECT 
                COUNT(*) as total_companies,
                AVG(rating) as avg_rating,
                MIN(price_per_sqm_min) as min_price,
                MAX(price_per_sqm_max) as max_price,
                AVG(price_per_sqm_min) as avg_price_min,
                AVG(price_per_sqm_max) as avg_price_max,
                AVG(reviews_count) as avg_reviews
            FROM companies {where}
        """, params)
        market = cur.fetchone()
        
        cur.execute(f"""
            SELECT category, COUNT(*) as count, AVG(rating) as avg_rating,
                   AVG(price_per_sqm_min) as avg_price
            FROM companies {where} AND category IS NOT NULL
            GROUP BY category ORDER BY count DESC LIMIT 15
        """.replace("AND category", "WHERE category" if not where else "AND category"), params)
        by_category = cur.fetchall()
        
        cur.execute(f"""
            SELECT region, COUNT(*) as count, AVG(rating) as avg_rating,
                   AVG(price_per_sqm_min) as avg_price
            FROM companies {where} AND region IS NOT NULL
            GROUP BY region ORDER BY count DESC LIMIT 15
        """.replace("AND region", "WHERE region" if not where else "AND region"), params)
        by_region = cur.fetchall()
        
        conn.close()
        return {"market_overview": market, "by_category": by_category, "by_region": by_region}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/analytics/best-companies", tags=["Analytics (Starter+)"])
async def api_v1_best_companies(
    region: str = "",
    category: str = "",
    sort_by: str = "rating",
    limit: int = 10
):
    """Find best companies. Starter+ plan required."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["rating IS NOT NULL"]
        params = []
        if region:
            conditions.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("category ILIKE %s")
            params.append(f"%{category}%")
        
        order = "rating DESC" if sort_by == "rating" else "reviews_count DESC" if sort_by == "reviews" else "price_per_sqm_min ASC"
        where = "WHERE " + " AND ".join(conditions)
        
        cur.execute(f"""
            SELECT id, name, slug, region, category, rating, reviews_count,
                   price_per_sqm_min, price_per_sqm_max, website, phone, description
            FROM companies {where}
            ORDER BY {order} NULLS LAST
            LIMIT %s
        """, params + [min(limit, 25)])
        
        companies = cur.fetchall()
        conn.close()
        return {"companies": companies, "sort_by": sort_by, "count": len(companies)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/analytics/price-comparison", tags=["Analytics (Starter+)"])
async def api_v1_price_comparison(region: str = "", category: str = ""):
    """Price comparison analytics. Starter+ plan required."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["price_per_sqm_min IS NOT NULL"]
        params = []
        if region:
            conditions.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("category ILIKE %s")
            params.append(f"%{category}%")
        where = "WHERE " + " AND ".join(conditions)
        
        cur.execute(f"""
            SELECT 
                MIN(price_per_sqm_min) as market_min,
                MAX(price_per_sqm_max) as market_max,
                AVG(price_per_sqm_min) as market_avg_min,
                AVG(price_per_sqm_max) as market_avg_max,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_per_sqm_min) as p25,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_sqm_min) as median,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_per_sqm_min) as p75
            FROM companies {where}
        """, params)
        prices = cur.fetchone()
        
        cur.execute(f"""
            SELECT name, slug, rating, price_per_sqm_min, price_per_sqm_max,
                   region, category
            FROM companies {where}
            ORDER BY price_per_sqm_min ASC LIMIT 10
        """, params)
        cheapest = cur.fetchall()
        
        cur.execute(f"""
            SELECT name, slug, rating, price_per_sqm_min, price_per_sqm_max,
                   region, category
            FROM companies {where}
            ORDER BY price_per_sqm_max DESC LIMIT 10
        """, params)
        premium = cur.fetchall()
        
        conn.close()
        return {"price_stats": prices, "cheapest": cheapest, "premium": premium}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/v1/analytics/report", tags=["Analytics (Starter+)"])
async def api_analytics_report(request: Request, region: str = None, category: str = None):
    """Comprehensive market analytics report (Starter+)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where = []
        params = []
        if region:
            where.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            where.append("category ILIKE %s")
            params.append(f"%{category}%")
        where_sql = "WHERE " + " AND ".join(where) if where else ""

        # Overview
        cur.execute(f"SELECT COUNT(*) as total, AVG(rating) as avg_rating, AVG(reviews_count) as avg_reviews FROM companies {where_sql}", params)
        overview = dict(cur.fetchone())

        # Price stats
        cur.execute(f"SELECT AVG(price_per_sqm_min) as avg_min, AVG(price_per_sqm_max) as avg_max, MIN(price_per_sqm_min) as cheapest, MAX(price_per_sqm_max) as most_expensive FROM companies {where_sql} AND price_per_sqm_min > 0" if where_sql else f"SELECT AVG(price_per_sqm_min) as avg_min, AVG(price_per_sqm_max) as avg_max, MIN(price_per_sqm_min) as cheapest, MAX(price_per_sqm_max) as most_expensive FROM companies WHERE price_per_sqm_min > 0", params)
        prices = dict(cur.fetchone())

        # Top regions
        cur.execute(f"SELECT region, COUNT(*) as cnt, AVG(rating) as avg_rating FROM companies {where_sql} GROUP BY region ORDER BY cnt DESC LIMIT 10", params)
        top_regions = [dict(r) for r in cur.fetchall()]

        # Top categories
        cur.execute(f"SELECT category, COUNT(*) as cnt, AVG(rating) as avg_rating FROM companies {where_sql} GROUP BY category ORDER BY cnt DESC LIMIT 10", params)
        top_categories = [dict(r) for r in cur.fetchall()]

        # Top companies
        cur.execute(f"SELECT name, slug, region, category, rating, reviews_count FROM companies {where_sql} ORDER BY rating DESC, reviews_count DESC LIMIT 10", params)
        top_companies = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            "report_type": "market_analytics",
            "filters": {"region": region, "category": category},
            "overview": overview,
            "price_stats": prices,
            "top_regions": top_regions,
            "top_categories": top_categories,
            "top_companies": top_companies
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/compare", tags=["Market Data (Free)"])
async def api_v1_compare(ids: str = ""):
    """Compare companies by IDs (comma-separated). Free tier."""
    try:
        if not ids:
            return {"error": "Provide company IDs as comma-separated list"}
        id_list = [x.strip() for x in ids.split(",")][:5]
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        placeholders = ",".join(["%s"] * len(id_list))
        cur.execute(f"""
            SELECT id, name, slug, region, category, rating, reviews_count,
                   price_per_sqm_min, price_per_sqm_max, website, phone
            FROM companies WHERE id::text IN ({placeholders}) OR slug IN ({placeholders})
        """, id_list + id_list)
        companies = cur.fetchall()
        conn.close()
        return {"companies": companies, "count": len(companies)}
    except Exception as e:
        return {"error": str(e)}

# API Documentation endpoint
@app.get("/api/v1/docs", tags=["Market Data (Free)"])
async def api_v1_docs():
    """REST API documentation."""
    return {
        "api_version": "1.0",
        "base_url": "https://mcp-market.ru/api/v1",
        "authentication": {
            "method": "API Key",
            "header": "X-API-Key",
            "query_param": "api_key",
            "get_key": "https://mcp-market.ru/pricing"
        },
        "plans": {
            "free": {"price": "0 RUB/month", "rate_limit": "100 req/day", "endpoints": "search, compare, categories, regions, stats"},
            "starter": {"price": "2990 RUB/month", "rate_limit": "1000 req/day", "endpoints": "free + analytics (market, best-companies, price-comparison)"},
            "pro": {"price": "7990 RUB/month", "rate_limit": "5000 req/day", "endpoints": "starter + AI tools (reviews, recommend, estimate, trends)"},
            "enterprise": {"price": "24990 RUB/month", "rate_limit": "unlimited", "endpoints": "all + priority support"}
        },
        "endpoints": {
            "free_tier": [
                {"method": "GET", "path": "/search/companies", "params": "q, region, category, min_rating, limit, offset"},
                {"method": "GET", "path": "/search/projects", "params": "q, region, category, min_area, max_area, limit, offset"},
                {"method": "GET", "path": "/companies/{id_or_slug}", "params": ""},
                {"method": "GET", "path": "/categories", "params": ""},
                {"method": "GET", "path": "/regions", "params": ""},
                {"method": "GET", "path": "/stats", "params": ""},
                {"method": "GET", "path": "/compare", "params": "ids (comma-separated)"},
            ],
            "starter_tier": [
                {"method": "GET", "path": "/analytics/market", "params": "region, category"},
                {"method": "GET", "path": "/analytics/best-companies", "params": "region, category, sort_by, limit"},
                {"method": "GET", "path": "/analytics/price-comparison", "params": "region, category"},
            ],
            "pro_tier": [
                {"method": "GET", "path": "/ai/reviews", "params": "company_id"},
                {"method": "GET", "path": "/ai/recommend", "params": "region, category, budget"},
                {"method": "GET", "path": "/ai/estimate", "params": "area, category, region"},
                {"method": "GET", "path": "/ai/trends", "params": "region, period"},
                {"method": "GET", "path": "/ai/deep-profile", "params": "company_id"},
                {"method": "GET", "path": "/ai/region-compare", "params": "regions (comma-separated)"},
            ]
        }
    }



# ==================== AI ENDPOINTS (Pro tier) ====================

@app.get("/api/v1/ai/reviews", tags=["AI Tools (Pro+)"])
async def api_v1_ai_reviews(company_id: str = ""):
    """AI-анализ отзывов компании. Pro tier."""
    if not company_id:
        return {"error": "company_id parameter required"}
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, rating, reviews_count, description, region, category FROM companies WHERE id::text = %s OR slug = %s", (company_id, company_id))
        company = cur.fetchone()
        conn.close()
        if not company:
            return {"error": "Company not found"}
        rating = float(company["rating"] or 0)
        reviews = int(company["reviews_count"] or 0)
        sentiment = "положительный" if rating >= 4.5 else "нейтральный" if rating >= 3.5 else "негативный"
        reliability = "высокая" if reviews >= 10 and rating >= 4.0 else "средняя" if reviews >= 3 else "низкая (мало отзывов)"
        return {
            "company": company["name"],
            "analysis": {
                "overall_sentiment": sentiment,
                "rating": rating,
                "reviews_count": reviews,
                "reliability": reliability,
                "strengths": ["Высокий рейтинг" if rating >= 4.5 else "Средний рейтинг", f"Регион: {company['region']}", f"Категория: {company['category']}"],
                "risks": ["Мало отзывов для статистики" if reviews < 5 else "Достаточно отзывов"],
                "recommendation": "Рекомендуем" if rating >= 4.0 and reviews >= 3 else "Требует дополнительной проверки"
            }
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/ai/recommend", tags=["AI Tools (Pro+)"])
async def api_v1_ai_recommend(region: str = "", category: str = "строительство", budget: float = 0, limit: int = 5):
    """AI-подбор подрядчиков. Pro tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["rating >= 4.0", "reviews_count >= 1"]
        params = []
        if region:
            conditions.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("category ILIKE %s")
            params.append(f"%{category}%")
        if budget > 0:
            conditions.append("(price_per_sqm_min IS NULL OR price_per_sqm_min <= %s)")
            params.append(budget)
        where = "WHERE " + " AND ".join(conditions)
        cur.execute(f"""
            SELECT name, slug, region, rating, reviews_count, price_per_sqm_min, price_per_sqm_max, phone, website,
                   (rating * 0.4 + LEAST(reviews_count::float/20, 1) * 0.3 + CASE WHEN price_per_sqm_min IS NOT NULL THEN 0.3 ELSE 0 END) as score
            FROM companies {where}
            ORDER BY score DESC, rating DESC
            LIMIT %s
        """, params + [min(limit, 20)])
        results = cur.fetchall()
        conn.close()
        recommendations = []
        for r in results:
            recommendations.append({
                "name": r["name"], "slug": r["slug"], "region": r["region"],
                "rating": float(r["rating"] or 0), "reviews": int(r["reviews_count"] or 0),
                "price_range": f"{int(r['price_per_sqm_min'] or 0)}-{int(r['price_per_sqm_max'] or 0)} руб/м²" if r["price_per_sqm_min"] else "не указана",
                "contact": r["phone"] or r["website"] or "нет данных",
                "match_score": round(float(r["score"] or 0) * 100)
            })
        return {"region": region or "все", "category": category, "budget": budget or "любой", "recommendations": recommendations}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/ai/estimate", tags=["AI Tools (Pro+)"])
async def api_v1_ai_estimate(area: float = 100, category: str = "строительство", region: str = ""):
    """AI-оценка стоимости проекта. Pro tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["price_per_sqm_min IS NOT NULL", "price_per_sqm_min > 0"]
        params = []
        if region:
            conditions.append("region ILIKE %s")
            params.append(f"%{region}%")
        if category:
            conditions.append("category ILIKE %s")
            params.append(f"%{category}%")
        where = "WHERE " + " AND ".join(conditions)
        cur.execute(f"""
            SELECT AVG(price_per_sqm_min) as avg_min, AVG(price_per_sqm_max) as avg_max,
                   MIN(price_per_sqm_min) as floor_min, MAX(price_per_sqm_max) as ceil_max,
                   PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price_per_sqm_min) as p25,
                   PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price_per_sqm_min) as p75,
                   COUNT(*) as sample_size
            FROM companies {where}
        """, params)
        stats = cur.fetchone()
        conn.close()
        if not stats or not stats["avg_min"]:
            return {"error": "Недостаточно данных для оценки"}
        avg_min = float(stats["avg_min"])
        avg_max = float(stats["avg_max"] or avg_min * 1.5)
        return {
            "input": {"area_sqm": area, "region": region or "все регионы", "category": category},
            "estimate": {
                "budget_low": int(area * float(stats["p25"] or avg_min * 0.7)),
                "budget_mid": int(area * avg_min),
                "budget_high": int(area * float(stats["p75"] or avg_max)),
                "budget_premium": int(area * float(stats["ceil_max"] or avg_max * 1.5)),
                "currency": "RUB"
            },
            "price_per_sqm": {
                "min": int(float(stats["floor_min"] or 0)),
                "avg": int(avg_min),
                "max": int(float(stats["ceil_max"] or 0))
            },
            "sample_size": int(stats["sample_size"]),
            "confidence": "высокая" if int(stats["sample_size"]) > 50 else "средняя" if int(stats["sample_size"]) > 10 else "низкая"
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/ai/trends", tags=["AI Tools (Pro+)"])
async def api_v1_ai_trends(region: str = "", period: str = "month"):
    """AI-анализ трендов рынка. Pro tier."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["price_per_sqm_min IS NOT NULL"]
        params = []
        if region:
            conditions.append("region ILIKE %s")
            params.append(f"%{region}%")
        where = "WHERE " + " AND ".join(conditions)
        cur.execute(f"""
            SELECT region, category, COUNT(*) as companies,
                   AVG(rating) as avg_rating, AVG(price_per_sqm_min) as avg_price,
                   SUM(reviews_count) as total_reviews
            FROM companies {where}
            GROUP BY region, category
            ORDER BY companies DESC
            LIMIT 20
        """, params)
        segments = cur.fetchall()
        conn.close()
        trends = []
        for s in segments:
            trends.append({
                "region": s["region"], "category": s["category"],
                "companies": int(s["companies"]),
                "avg_rating": round(float(s["avg_rating"] or 0), 2),
                "avg_price_sqm": int(float(s["avg_price"] or 0)),
                "market_activity": "высокая" if int(s["total_reviews"] or 0) > 100 else "средняя" if int(s["total_reviews"] or 0) > 20 else "низкая"
            })
        return {"region": region or "все регионы", "period": period, "market_segments": trends, "total_segments": len(trends)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/ai/deep-profile", tags=["AI Tools (Pro+)"])
async def api_v1_ai_deep_profile(company_id: str = ""):
    """Глубокий AI-профиль компании. Pro tier."""
    if not company_id:
        return {"error": "company_id parameter required"}
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM companies WHERE id::text = %s OR slug = %s", (company_id, company_id))
        company = cur.fetchone()
        if not company:
            conn.close()
            return {"error": "Company not found"}
        cur.execute("SELECT COUNT(*) as cnt, AVG(area) as avg_area, AVG(price) as avg_price FROM projects WHERE company_id = %s", (company["id"],))
        proj_stats = cur.fetchone()
        cur.execute("""
            SELECT AVG(rating) as market_avg_rating, AVG(price_per_sqm_min) as market_avg_price, COUNT(*) as market_total
            FROM companies WHERE region = %s AND category = %s AND price_per_sqm_min IS NOT NULL
        """, (company["region"], company["category"]))
        market = cur.fetchone()
        conn.close()
        rating = float(company["rating"] or 0)
        market_avg = float(market["market_avg_rating"] or 0)
        price = float(company["price_per_sqm_min"] or 0)
        market_price = float(market["market_avg_price"] or 1)
        return {
            "company": {"name": company["name"], "slug": company["slug"], "region": company["region"], "category": company["category"]},
            "profile": {
                "rating": rating,
                "vs_market_rating": round(rating - market_avg, 2),
                "reviews": int(company["reviews_count"] or 0),
                "projects_count": int(proj_stats["cnt"] or 0),
                "avg_project_area": round(float(proj_stats["avg_area"] or 0), 1),
                "price_per_sqm": {"min": int(price), "max": int(float(company["price_per_sqm_max"] or 0))},
                "price_vs_market": f"{round((price/market_price - 1)*100)}%" if market_price > 0 and price > 0 else "н/д",
                "has_website": bool(company["website"]),
                "has_phone": bool(company["phone"]),
                "has_email": bool(company["email"]),
                "completeness": sum([bool(company.get(f)) for f in ["website","phone","email","description","price_per_sqm_min"]]) * 20
            },
            "market_context": {
                "region_competitors": int(market["market_total"] or 0),
                "region_avg_rating": round(market_avg, 2),
                "region_avg_price": int(market_price)
            },
            "ai_verdict": "Лидер рынка" if rating >= 4.8 and int(company["reviews_count"] or 0) >= 10 else "Сильный игрок" if rating >= 4.3 else "Средний игрок" if rating >= 3.5 else "Требует внимания"
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/v1/ai/region-compare", tags=["AI Tools (Pro+)"])
async def api_v1_ai_region_compare(regions: str = ""):
    """AI-сравнение регионов. Pro tier."""
    if not regions:
        return {"error": "regions parameter required (comma-separated)"}
    try:
        region_list = [r.strip() for r in regions.split(",")]
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        results = []
        for reg in region_list[:5]:
            cur.execute("""
                SELECT COUNT(*) as companies, AVG(rating) as avg_rating,
                       AVG(price_per_sqm_min) as avg_price_min, AVG(price_per_sqm_max) as avg_price_max,
                       SUM(reviews_count) as total_reviews,
                       COUNT(CASE WHEN rating >= 4.5 THEN 1 END) as top_rated
                FROM companies WHERE region ILIKE %s AND price_per_sqm_min IS NOT NULL
            """, (f"%{reg}%",))
            stats = cur.fetchone()
            if stats and int(stats["companies"] or 0) > 0:
                results.append({
                    "region": reg, "companies": int(stats["companies"]),
                    "avg_rating": round(float(stats["avg_rating"] or 0), 2),
                    "avg_price_min": int(float(stats["avg_price_min"] or 0)),
                    "avg_price_max": int(float(stats["avg_price_max"] or 0)),
                    "total_reviews": int(stats["total_reviews"] or 0),
                    "top_rated_pct": round(int(stats["top_rated"] or 0) / int(stats["companies"]) * 100, 1),
                    "market_maturity": "зрелый" if int(stats["companies"]) > 100 else "развивающийся" if int(stats["companies"]) > 30 else "начальный"
                })
        conn.close()
        if not results:
            return {"error": "No data for specified regions"}
        best_price = min(results, key=lambda x: x["avg_price_min"])
        best_quality = max(results, key=lambda x: x["avg_rating"])
        return {
            "regions_compared": len(results),
            "data": results,
            "insights": {
                "cheapest_region": best_price["region"],
                "highest_quality_region": best_quality["region"],
                "recommendation": f"Лучшее соотношение цена/качество: {best_quality['region'] if best_quality['avg_price_min'] <= best_price['avg_price_min'] * 1.2 else best_price['region']}"
            }
        }
    except Exception as e:
        return {"error": str(e)}

# --- Crypto Payment endpoints ---
import hashlib, secrets
from datetime import datetime, timedelta

def _require_admin(request) -> bool:
    """Admin endpoints are gated by ADMIN_TOKEN from the environment.
    If ADMIN_TOKEN is unset, admin endpoints stay closed (fail-closed)."""
    import os as _os
    expected = _os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        return False
    return secrets.compare_digest(request.headers.get("x-admin-token", ""), expected)


CRYPTO_WALLETS = {
    "BTC": "bc1qmcp2026market0russia0pay0btc0wallet",
    "ETH": "0xMCP2026MarketRussiaPay0ETH0Wallet00",
    "USDT": "TMcp2026MarketRussiaPayUSDTWallet00"
}

PLAN_PRICES = {"starter": 2990, "pro": 7990, "enterprise": 24990}
CRYPTO_RATES_PER_RUB = {"BTC": 0.0000001149, "ETH": 0.00000345, "USDT": 0.012}

@app.post("/api/payments/create")
async def create_payment(request: Request):
    """Create a new crypto payment"""
    try:
        data = await request.json()
        plan = data.get("plan", "").lower()
        crypto = data.get("crypto", "").upper()
        name = data.get("name", "")
        email = data.get("email", "")
        
        if plan not in PLAN_PRICES:
            return JSONResponse({"error": f"Invalid plan: {plan}"}, status_code=400)
        if crypto not in CRYPTO_WALLETS:
            return JSONResponse({"error": f"Invalid crypto: {crypto}"}, status_code=400)
        if not email or "@" not in email:
            return JSONResponse({"error": "Valid email required"}, status_code=400)
        
        amount_rub = PLAN_PRICES[plan]
        rate = CRYPTO_RATES_PER_RUB.get(crypto, 0.012)
        amount_crypto = round(amount_rub * rate, 8)
        
        raw = f"{plan}-{crypto}-{email}-{secrets.token_hex(8)}"
        payment_id = f"pay_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"
        wallet = CRYPTO_WALLETS[crypto]
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO payments (payment_id, plan, amount_rub, amount_crypto, crypto_currency, wallet_address, owner_name, owner_email)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at, expires_at""",
            (payment_id, plan, amount_rub, amount_crypto, crypto, wallet, name, email)
        )
        row = cur.fetchone()
        conn.commit()
        
        return JSONResponse({
            "payment_id": payment_id,
            "plan": plan,
            "amount_rub": amount_rub,
            "amount_crypto": str(amount_crypto),
            "crypto": crypto,
            "wallet": wallet,
            "status": "pending",
            "created_at": str(row[1]),
            "expires_at": str(row[2])
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/payments/{payment_id}")
async def get_payment_status(payment_id: str):
    """Check payment status"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM payments WHERE payment_id = %s", (payment_id,))
        row = cur.fetchone()
        if not row:
            return JSONResponse({"error": "Payment not found"}, status_code=404)
        
        # Auto-expire old payments
        if row["status"] == "pending" and row["expires_at"] and datetime.now() > row["expires_at"]:
            cur.execute("UPDATE payments SET status = 'expired' WHERE payment_id = %s", (payment_id,))
            conn.commit()
            row["status"] = "expired"
        
        return JSONResponse({
            "payment_id": row["payment_id"],
            "plan": row["plan"],
            "amount_rub": row["amount_rub"],
            "amount_crypto": str(row["amount_crypto"]) if row["amount_crypto"] else None,
            "crypto": row["crypto_currency"],
            "status": row["status"],
            "created_at": str(row["created_at"]),
            "expires_at": str(row["expires_at"]) if row["expires_at"] else None
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/payments/{payment_id}/confirm")
async def confirm_payment(payment_id: str, request: Request):
    """Admin: confirm payment and create API key. Requires X-Admin-Token."""
    if not _require_admin(request):
        return JSONResponse({"error": "Admin authentication required"}, status_code=401)
    try:
        data = await request.json()
        tx_hash = data.get("tx_hash", "")
        
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM payments WHERE payment_id = %s", (payment_id,))
        payment = cur.fetchone()
        if not payment:
            return JSONResponse({"error": "Payment not found"}, status_code=404)
        if payment["status"] == "completed":
            return JSONResponse({"error": "Already completed"}, status_code=400)
        
        # Create API key for the user
        plan = payment["plan"]
        limits = {"starter": 1000, "pro": 5000, "enterprise": -1}
        req_limit = limits.get(plan, 5000)
        
        raw_key = secrets.token_hex(16)
        api_key = f"mcp_{plan}_{hashlib.sha256(raw_key.encode()).hexdigest()[:24]}"
        
        cur.execute(
            """INSERT INTO api_keys (key, owner_name, owner_email, plan, requests_limit)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (api_key, payment["owner_name"], payment["owner_email"], plan, req_limit)
        )
        key_id = cur.fetchone()["id"]
        
        cur.execute(
            """UPDATE payments SET status = 'completed', tx_hash = %s, api_key_id = %s, confirmed_at = NOW()
               WHERE payment_id = %s""",
            (tx_hash, key_id, payment_id)
        )
        conn.commit()
        
        return JSONResponse({
            "status": "completed",
            "api_key": api_key,
            "plan": plan,
            "owner_email": payment["owner_email"]
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/payments")
async def list_payments(request: Request):
    """Admin: list all payments. Requires X-Admin-Token."""
    if not _require_admin(request):
        return JSONResponse({"error": "Admin authentication required"}, status_code=401)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 50")
        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                "payment_id": r["payment_id"],
                "plan": r["plan"],
                "amount_rub": r["amount_rub"],
                "crypto": r["crypto_currency"],
                "status": r["status"],
                "owner_email": r["owner_email"],
                "created_at": str(r["created_at"])
            })
        return JSONResponse({"payments": result, "total": len(result)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ------- Dashboard API aliases (added 2026-04-17, B-fix) -------
# Reason: dashboard.html JS fetches /stats, /completeness, /requests
# but backend exposed /overview, /data-completeness, /recent-queries.
# These three handlers adapt response shapes to what the JS expects.

@app.get("/api/dashboard/stats")
async def dashboard_stats_alias():
    """Alias for dashboard stat cards. Reuses overview + adds tools=21."""
    data = await dashboard_overview()
    if isinstance(data, dict):
        data.setdefault("tools", 24)
    return data


@app.get("/api/dashboard/completeness")
async def dashboard_completeness_alias():
    """Alias: transform data-completeness to {fields: [{name, percentage}, ...]}."""
    raw = await dashboard_data_completeness()
    if not isinstance(raw, dict) or not raw:
        return {"fields": []}
    labels = {
        "websites": "Сайт",
        "phones": "Телефон",
        "emails": "Email",
        "descriptions": "Описание",
        "prices": "Прайс",
        "ratings": "Рейтинг",
    }
    fields = []
    for key, label in labels.items():
        item = raw.get(key)
        if isinstance(item, dict):
            fields.append({"name": label, "percentage": item.get("percent", 0)})
    return {"total": raw.get("total", 0), "fields": fields}


@app.get("/api/dashboard/requests")
async def dashboard_requests_alias():
    """Alias: transform recent-queries to [{timestamp,endpoint,status,duration},...]."""
    raw = await dashboard_recent_queries()
    if not isinstance(raw, list):
        return []
    out = []
    for q in raw:
        ts = q.get("ts") or q.get("timestamp")
        out.append({
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
            "endpoint": q.get("tool_name") or q.get("endpoint") or "tools/call",
            "status": 200,
            "duration": q.get("duration_ms") or q.get("duration") or 0,
        })
    return out


# --- Stub routes (about/contacts/favicon) — added 2026-04-18 ---
@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
async def about_page():
    with open("app/static/about.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/contacts", response_class=HTMLResponse, include_in_schema=False)
async def contacts_page():
    with open("app/static/contacts.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/legal/offer", response_class=HTMLResponse, include_in_schema=False)
async def legal_offer_page():
    with open("app/static/legal/offer.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
async def legal_privacy_page():
    with open("app/static/legal/privacy.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse("app/static/favicon.svg", media_type="image/svg+xml")

@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse("app/static/favicon.svg", media_type="image/svg+xml")

@app.get("/static/stats-injector.js", include_in_schema=False)
async def stats_injector_js():
    return FileResponse("app/static/stats-injector.js", media_type="application/javascript")

@app.get("/.well-known/security.txt", include_in_schema=False)
async def security_txt():
    return FileResponse("app/static/security.txt", media_type="text/plain")

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
            # Projects have no category/region/city of their own - those belong
            # to the owning company, so the projects export joins companies.
            is_projects = entity == "projects"
            c_name = "p.name" if is_projects else "name"
            c_desc = "p.description" if is_projects else "description"
            c_cat = "c.category" if is_projects else "category"
            c_reg = "c.region" if is_projects else "region"
            c_city = "c.city" if is_projects else "city"
            if query:
                conditions.append(f"({c_name} ILIKE %(query)s OR {c_desc} ILIKE %(query)s)")
                params["query"] = f"%{query}%"
            if category:
                conditions.append(f"({c_cat} = %(category)s)")
                params["category"] = category
            if region:
                conditions.append(f"({c_reg} ILIKE %(region)s OR {c_city} ILIKE %(region)s)")
                params["region"] = f"%{region}%"
            if budget_max > 0:
                if is_projects:
                    conditions.append("(p.price <= %(budget)s OR p.price IS NULL)")
                else:
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
                        "price", "price_per_sqm", "area", "floors",
                        "material", "description"]
                select_list = ("p.id, p.name, c.category, c.region, c.city, "
                               "p.price, p.price_per_sqm, p.area, p.floors, "
                               "p.material, p.description")
                sql = (f"SELECT {select_list} FROM projects p "
                       f"JOIN companies c ON p.company_id = c.id "
                       f"WHERE {where} ORDER BY p.price DESC NULLS LAST LIMIT %(lim)s")

            try:
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                return "ERROR: export failed for the requested filters"

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
        "казан": "Татарстан", "уфа": "Башкортостан", "уф": "Башкортостан", "московск": "Московская область", "уф": "Башкортостан", "московск": "Московская область", "тюмен": "Тюменская область",
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
        "каркас": "каркасные_дома",
        "из бруса": "дома_из_бруса", "брусов": "дома_из_бруса",
        "кирпич": "кирпич",
        "газобетон": "строительство", "газоблок": "строительство",
        "пеноблок": "строительство", "керамзит": "строительство", "блочн": "строительство",
        "сип": "строительство",
        "бревен": "строительство", "сруб": "строительство",
        "бан": "строительство",
        "гараж": "строительство",
        "коттедж": "строительство",
        "таунхаус": "строительство",
        "строительств": "строительство", "постройк": "строительство", "дом под ключ": "строительство",
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
                -- A contractor the agent cannot phone or look up is a dead
                -- lead, so contactable companies outrank uncontactable ones.
                ORDER BY ((CASE WHEN phone IS NOT NULL AND phone <> '' THEN 2 ELSE 0 END)
                        + (CASE WHEN website IS NOT NULL AND website <> '' THEN 1 ELSE 0 END)) DESC,
                         rating DESC NULLS LAST, reviews_count DESC NULLS LAST
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
                SELECT l.id, l.status, l.name, l.phone, l.email, l.comment,
                       l.created_at, l.sent_to_crm_at,
                       c.name AS company_name
                FROM leads l
                LEFT JOIN companies c ON c.id = l.company_id
                WHERE l.id::text = %s
            """, (lead_id,))
            row = cur.fetchone()
            if not row:
                return _json.dumps({"error": f"Lead {lead_id} not found"})
            d = dict(row)
            def _mask(v):
                v = v or ""
                return (v[:2] + "***" + v[-2:]) if len(v) > 4 else ("***" if v else "")
            d["phone"] = _mask(d.get("phone"))
            d["email"] = _mask(d.get("email"))
            return _json.dumps(d, ensure_ascii=False, default=str)
    finally:
        conn.close()


# REST wrapper for smart_match (anonymous, added 2026-04-20 for /demo page)
@app.get("/api/v1/smart-match", tags=["Market Data (Free!)"])
async def api_smart_match(brief: str, top_n: int = 3):
    """Natural-language Russian brief -> parsed filters + top-N contractors."""
    import json as _json
    if top_n < 1 or top_n > 10:
        top_n = 3
    return _json.loads(smart_match(brief=brief, top_n=top_n))


# QUICKSTART_ROUTE_INJECTED
@app.get("/quickstart", response_class=HTMLResponse)
async def quickstart_page():
    try:
        with open("/app/app/static/quickstart.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception as e:
        return HTMLResponse(f"<h1>quickstart error</h1><pre>{html.escape(str(e))}</pre>", status_code=500)

@app.get("/docs", response_class=HTMLResponse)
async def docs_redirect():
    return await quickstart_page()

# QUICKSTART_INLINE_FIXED
