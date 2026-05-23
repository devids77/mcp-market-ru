# Update index.html to show 21 tools
with open('/opt/mcp-market/app/static/index.html', 'r') as f:
    content = f.read()

# Update tool count
content = content.replace('МСП Инструменты (18)', 'МСП Инструменты (21)')
content = content.replace("18 MCP инструментов", "21 MCP инструментов")

# Add new tools to the grid - find the last tool and add after it
old_tools_end = "project_estimator<span"
new_tools_html = """project_estimator<span class="ml-1 text-xs bg-pink-500 px-1 rounded">NEW</span></span>
            <span class="status-ring px-3 py-1.5 bg-gray-800 rounded-lg text-sm">trend_analyzer<span class="ml-1 text-xs bg-pink-500 px-1 rounded">NEW</span></span>
            <span class="status-ring px-3 py-1.5 bg-gray-800 rounded-lg text-sm">company_deep_profile<span class="ml-1 text-xs bg-pink-500 px-1 rounded">NEW</span></span>
            <span class="status-ring px-3 py-1.5 bg-gray-800 rounded-lg text-sm">region_comparison<span"""

content = content.replace(old_tools_end, new_tools_html)

with open('/opt/mcp-market/app/static/index.html', 'w') as f:
    f.write(content)
print("Dashboard updated to 21 tools")
