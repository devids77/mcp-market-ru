"""
Import projects from СкандиЭкоДом API (147.45.214.46:8100) into MCP Market database.
Run: python3 /opt/mcp-market/scripts/import_scandieco.py
"""
import json
import uuid
import psycopg2
import psycopg2.extras
import requests

DB = "postgresql://mcpuser:McpMarket2026Secure@127.0.0.1:5432/mcpmarket"
API_URL = "http://147.45.214.46:8100/projects/search"
COMPANY_NAME = "СкандиЭкоДом"


def get_db():
    conn = psycopg2.connect(DB)
    conn.autocommit = True
    return conn


def fetch_all_projects():
    """Fetch all projects from СкандиЭкоДом API."""
    all_projects = []
    
    # Try fetching with increasing limits
    for limit in [50, 100, 150, 200]:
        try:
            r = requests.get(API_URL, params={"limit": limit}, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > len(all_projects):
                    all_projects = data
                elif isinstance(data, dict) and "items" in data:
                    all_projects = data["items"]
                elif isinstance(data, dict) and "results" in data:
                    all_projects = data["results"]
        except Exception as e:
            print(f"  Error with limit={limit}: {e}")
    
    # If single limit didn't work, try pagination
    if len(all_projects) <= 1:
        print("Trying different sort options...")
        for sort in ["price_asc", "price_desc", "area_asc", "area_desc"]:
            try:
                r = requests.get(API_URL, params={"limit": 50, "sort_by": sort}, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        for p in data:
                            if p not in all_projects:
                                all_projects.append(p)
            except:
                pass
    
    return all_projects


def get_detail(project_id):
    """Try to get detailed project info."""
    try:
        r = requests.get(f"http://147.45.214.46:8100/projects/{project_id}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None


def main():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Find or verify СкандиЭкоДом company
    cur.execute("SELECT id FROM companies WHERE name = %s", (COMPANY_NAME,))
    row = cur.fetchone()
    if not row:
        print(f"Company '{COMPANY_NAME}' not found in database!")
        return
    company_id = str(row["id"])
    print(f"Company: {COMPANY_NAME} (ID: {company_id})")
    
    # Count existing projects
    cur.execute("SELECT COUNT(*) as cnt FROM projects WHERE company_id = %s", (company_id,))
    existing = cur.fetchone()["cnt"]
    print(f"Existing projects: {existing}")
    
    # Fetch from API
    print(f"\nFetching projects from {API_URL}...")
    projects = fetch_all_projects()
    print(f"Fetched: {len(projects)} projects")
    
    if not projects:
        print("No projects fetched! Check API.")
        return
    
    # Show first project for debugging
    if projects:
        print(f"\nSample project:")
        print(json.dumps(projects[0], indent=2, ensure_ascii=False))
    
    # Import
    imported = 0
    skipped = 0
    
    for p in projects:
        title = p.get("title") or p.get("name") or p.get("id", "")
        area = p.get("area_m2") or p.get("area")
        
        if not title or not area:
            skipped += 1
            continue
        
        # Check duplicate by title
        cur.execute("SELECT 1 FROM projects WHERE name = %s AND company_id = %s", (title, company_id))
        if cur.fetchone():
            skipped += 1
            continue
        
        # Parse fields
        floors_raw = p.get("floors", "")
        floors = None
        if floors_raw:
            if "2" in str(floors_raw):
                floors = 2
            elif "3" in str(floors_raw):
                floors = 3
            elif "1" in str(floors_raw):
                floors = 1
        
        price = None
        price_from = p.get("price_from")
        price_to = p.get("price_to")
        if price_from:
            price = int(price_from)
        
        price_desc = None
        if price_from and price_to:
            price_desc = f"от {int(price_from):,} до {int(price_to):,} ₽".replace(",", " ")
        
        price_per_sqm = None
        if price and area:
            price_per_sqm = int(price / area)
        
        bedrooms = p.get("bedrooms")
        bathrooms = p.get("bathrooms")
        style = p.get("style")
        site_url = p.get("site_url")
        
        pid = str(uuid.uuid4())
        
        cur.execute("""
            INSERT INTO projects (id, company_id, name, area, floors, bedrooms, bathrooms, 
                                  material, style, price, price_per_sqm, price_description, 
                                  url, source, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (
            pid, company_id, title, area, floors, bedrooms, bathrooms,
            "каркас", style, price, price_per_sqm, price_desc,
            site_url, "scandiecodom_api",
            f"Каркасный дом {title}, {area} м², {floors_raw}. Компания СкандиЭкоДом."
        ))
        
        imported += 1
    
    # Update company project count
    cur.execute("""
        UPDATE companies SET projects_count = (
            SELECT COUNT(*) FROM projects WHERE company_id = %s
        ) WHERE id = %s
    """, (company_id, company_id))
    
    print(f"\n{'='*60}")
    print(f"DONE!")
    print(f"  Fetched from API: {len(projects)}")
    print(f"  Imported: {imported}")
    print(f"  Skipped (duplicates): {skipped}")
    
    # Final count
    cur.execute("SELECT COUNT(*) as cnt FROM projects WHERE company_id = %s", (company_id,))
    total = cur.fetchone()["cnt"]
    print(f"  Total projects for {COMPANY_NAME}: {total}")
    print(f"{'='*60}")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
