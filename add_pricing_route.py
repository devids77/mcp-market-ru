import re

with open("/opt/mcp-market/app/main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the dashboard route and add pricing route after the tasks route
pricing_route = '''

@app.get("/pricing", response_class=HTMLResponse)
@app.get("/pricing.html", response_class=HTMLResponse)
async def pricing_page():
    html_path = os.path.join(os.path.dirname(__file__), "static", "pricing.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Pricing page not found</h3>"
'''

# Insert before "# --- Tasks API endpoints"
marker = "# --- Tasks API endpoints"
if marker in content:
    content = content.replace(marker, pricing_route + "\n" + marker)
    print(f"SUCCESS: Inserted pricing route before '{marker}'")
else:
    # Try inserting after the tasks.html route
    marker2 = 'return "<h3>Tasks not found</h3>"'
    if marker2 in content:
        content = content.replace(marker2, marker2 + pricing_route)
        print(f"SUCCESS: Inserted pricing route after tasks route")
    else:
        # Fallback: insert before "if __name__"
        content = content.replace('if __name__', pricing_route + '\nif __name__')
        print("SUCCESS: Inserted pricing route before __main__")

with open("/opt/mcp-market/app/main.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
