"""Add monetization endpoints to main.py"""
import hashlib
import time

new_endpoints = '''

# ============ MONETIZATION ENDPOINTS ============

@app.post("/api/register")
async def register_api_key(request: Request):
    """Register new API key"""
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        email = data.get("email", "").strip()
        phone = data.get("phone", "")
        plan = data.get("plan", "free")
        
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
        
        return JSONResponse({
            "api_key": api_key,
            "plan": plan,
            "requests_limit": req_limit,
            "message": "API key created successfully"
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/leads/create")
async def create_lead(request: Request):
    """Create a lead (paid feature)"""
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
async def get_leads(status: str = "", limit: int = 50):
    """Get leads list"""
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


@app.get("/api/keys")
async def get_api_keys():
    """Get API keys stats (admin)"""
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
async def get_usage_stats():
    """Get usage statistics for billing"""
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
            "free": {"name": "Free", "price": 0, "requests_per_day": 100, "tools": 10},
            "starter": {"name": "Starter", "price": 2990, "requests_per_day": 1000, "tools": 15},
            "pro": {"name": "Pro", "price": 7990, "requests_per_day": 5000, "tools": 21},
            "enterprise": {"name": "Enterprise", "price": 24990, "requests_per_day": -1, "tools": 21}
        },
        "company_plans": {
            "basic": {"name": "Basic", "price": 0, "leads_per_month": 0},
            "premium": {"name": "Premium", "price": 4990, "leads_per_month": 20},
            "vip": {"name": "VIP", "price": 14990, "leads_per_month": -1}
        },
        "currency": "RUB"
    })

'''

# Read main.py
with open('/opt/mcp-market/app/main.py', 'r') as f:
    content = f.read()

# Find where to insert - before the last line or after the last endpoint
# Insert before "if __name__" or at the end
if 'if __name__' in content:
    content = content.replace('if __name__', new_endpoints + '\nif __name__')
else:
    content += new_endpoints

with open('/opt/mcp-market/app/main.py', 'w') as f:
    f.write(content)

print("SUCCESS: Monetization endpoints added to main.py")
print(f"File size: {len(content)} bytes")
