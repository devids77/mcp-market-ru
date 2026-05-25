import re

new_tools = '''

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
        
        result = "📊 MARKET TREND ANALYSIS\\n"
        result += "=" * 50 + "\\n\\n"
        
        if region or category:
            result += f"Filter: {region or 'all regions'}, {category or 'all categories'}\\n\\n"
        
        result += "🏢 TOP REGIONS BY COMPANY COUNT:\\n"
        for r in regions_data:
            price_info = f", price {r['avg_price_min']}-{r['avg_price_max']} ₽/m²" if r['avg_price_min'] else ""
            result += f"  • {r['region']}: {r['companies']} companies, ★{r['avg_rating']}, {r['total_reviews']} reviews{price_info}\\n"
        
        result += "\\n📋 TOP CATEGORIES:\\n"
        for c in categories_data:
            result += f"  • {c['category']}: {c['companies']} companies, ★{c['avg_rating']}, {c['total_reviews']} reviews\\n"
        
        result += "\\n⭐ QUALITY DISTRIBUTION:\\n"
        for q in quality_data:
            result += f"  • {q['quality_tier']}: {q['companies']} companies, ~{q['avg_reviews']} avg reviews\\n"
        
        if price_segments:
            result += "\\n💰 PRICE SEGMENTS:\\n"
            for p in price_segments:
                result += f"  • {p['price_segment']}: {p['companies']} companies, ★{p['avg_rating']}\\n"
        
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
                return "Company not found. Did you mean:\\n" + "\\n".join([f"  • {s['slug']} ({s['name']}, {s['region']})" for s in suggestions])
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
        
        result = f"🏗️ COMPANY DEEP PROFILE\\n"
        result += "=" * 50 + "\\n\\n"
        result += f"📌 {company['name']}\\n"
        result += f"   Slug: {company['slug']}\\n"
        result += f"   Region: {company['region']}\\n"
        result += f"   Category: {company['category']}\\n"
        result += f"   Rating: ★{company['rating']} ({company['reviews_count']} reviews)\\n"
        
        if company.get('phone'):
            result += f"   📞 Phone: {company['phone']}\\n"
        if company.get('email'):
            result += f"   📧 Email: {company['email']}\\n"
        if company.get('website'):
            result += f"   🌐 Website: {company['website']}\\n"
        if company.get('address'):
            result += f"   📍 Address: {company['address']}\\n"
        
        if company.get('price_per_sqm_min') or company.get('min_project_price'):
            result += "\\n💰 PRICING:\\n"
            if company.get('price_per_sqm_min'):
                result += f"   Per m²: {company['price_per_sqm_min']} - {company.get('price_per_sqm_max', 'N/A')} ₽\\n"
            if company.get('min_project_price'):
                result += f"   Project: from {company['min_project_price']} ₽\\n"
        
        if company.get('description'):
            desc = company['description'][:300]
            result += f"\\n📝 DESCRIPTION:\\n   {desc}...\\n" if len(company['description']) > 300 else f"\\n📝 DESCRIPTION:\\n   {desc}\\n"
        
        if projects:
            result += f"\\n🏠 PROJECTS ({len(projects)}):\\n"
            for p in projects:
                desc_short = (p['description'][:80] + '...') if p.get('description') and len(p['description']) > 80 else (p.get('description') or '')
                result += f"   • {p['name']}: {desc_short}\\n"
        
        if regional:
            result += f"\\n📊 MARKET POSITION (vs {regional['total_companies']} companies in {company['region']}/{company['category']}):\\n"
            rating_diff = round(float(company['rating'] or 0) - float(regional['avg_rating'] or 0), 2)
            result += f"   Rating: {'↑' if rating_diff > 0 else '↓'}{abs(rating_diff)} vs average ★{regional['avg_rating']}\\n"
            reviews_diff = int(company['reviews_count'] or 0) - int(regional['avg_reviews'] or 0)
            result += f"   Reviews: {'↑' if reviews_diff > 0 else '↓'}{abs(reviews_diff)} vs average {regional['avg_reviews']}\\n"
        
        if competitors:
            result += "\\n🏆 TOP COMPETITORS:\\n"
            for c in competitors:
                price = f", {c['price_per_sqm_min']}-{c['price_per_sqm_max']} ₽/m²" if c.get('price_per_sqm_min') else ""
                result += f"   • {c['name']} (★{c['rating']}, {c['reviews_count']} reviews{price})\\n"
        
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
        
        output = "🗺️ REGION COMPARISON\\n"
        output += "=" * 50 + "\\n"
        if category:
            output += f"Category filter: {category}\\n"
        output += "\\n"
        
        for r in results:
            phone_pct = round(r['with_phone'] / r['total_companies'] * 100) if r['total_companies'] else 0
            email_pct = round(r['with_email'] / r['total_companies'] * 100) if r['total_companies'] else 0
            
            output += f"📍 {r['region']}\\n"
            output += f"   Companies: {r['total_companies']} ({r['categories_count']} categories)\\n"
            output += f"   Rating: ★{r['avg_rating']} avg, ★{r['max_rating']} max ({r['rated_companies']} rated)\\n"
            output += f"   Reviews: {r['total_reviews']} total, ~{r['avg_reviews']} per company\\n"
            output += f"   Contacts: {r['with_phone']} phones ({phone_pct}%), {r['with_email']} emails ({email_pct}%)\\n"
            
            if r['with_prices'] > 0:
                output += f"   Prices: {r['with_prices']} companies, {r['avg_price_min']}-{r['avg_price_max']} ₽/m² avg, range {r['min_price']}-{r['max_price']} ₽/m²\\n"
            
            if r.get('top_categories'):
                cats = ", ".join([f"{c['category']}({c['cnt']})" for c in r['top_categories']])
                output += f"   Top categories: {cats}\\n"
            output += "\\n"
        
        # Winner summary
        if len(results) > 1:
            output += "🏆 COMPARISON SUMMARY:\\n"
            most_companies = max(results, key=lambda x: x['total_companies'])
            output += f"   Most companies: {most_companies['region']} ({most_companies['total_companies']})\\n"
            best_rated = max(results, key=lambda x: float(x['avg_rating'] or 0))
            output += f"   Best rated: {best_rated['region']} (★{best_rated['avg_rating']})\\n"
            most_reviews = max(results, key=lambda x: x['total_reviews'] or 0)
            output += f"   Most reviews: {most_reviews['region']} ({most_reviews['total_reviews']})\\n"
            best_contacts = max(results, key=lambda x: x['with_phone'])
            output += f"   Best contact coverage: {best_contacts['region']} ({best_contacts['with_phone']} phones)\\n"
        
        return output
    except Exception as e:
        return f"Error: {str(e)}"


'''

# Read the file
with open('/opt/mcp-market/app/main.py', 'r') as f:
    content = f.read()

# Find the line with @app.get("/api/companies/search")
marker = '@app.get("/api/companies/search")'
if marker in content:
    content = content.replace(marker, new_tools + marker)
    with open('/opt/mcp-market/app/main.py', 'w') as f:
        f.write(content)
    print("SUCCESS: 3 new MCP tools inserted before @app.get(/api/companies/search)")
else:
    print("ERROR: marker not found")

# Count total @mcp.tool() decorators
count = content.count('@mcp.tool()')
print(f"Total @mcp.tool() count: {count}")
