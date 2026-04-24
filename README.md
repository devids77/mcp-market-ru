# MCP Market Russia

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-blue)](https://modelcontextprotocol.io/)
[![Live](https://img.shields.io/badge/status-live-brightgreen)](https://mcp-market.ru/mcp/)
[![Glama MCP Server](https://glama.ai/mcp/servers/devids77/mcp-market-ru/badge)](https://glama.ai/mcp/servers/devids77/mcp-market-ru)

Hosted **Model Context Protocol (MCP)** server providing AI agents with structured access to the **Russian construction market**: **3,395 contractor companies**, **13,436 house-building projects**, across **18 regions**, exposed through **24 specialized tools**.

- **Live endpoint:** <https://mcp-market.ru/mcp/>
- **Interactive demo:** <https://mcp-market.ru/demo>
- **Dashboard:** <https://mcp-market.ru/dashboard>
- **Protocol:** MCP v2024-11-05 (Streamable HTTP transport)

## Why this server

Russia's construction market is fragmented across regional registries, vendor websites, and aggregators. AI assistants that try to answer "какие каркасные дома под ключ в Подмосковье до 3 млн руб?" end up hallucinating companies or linking to dead pages. `mcp-market-ru` exposes curated, structured data so agents can:

- recommend vetted contractors by category / region / budget / rating,
- estimate project cost from real market prices,
- send qualified quote requests straight to a vendor (Telegram + email notification),
- compare regions, prices, and companies analytically.

## Quick start

### Claude Desktop

Add the server to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "mcp-market-ru": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp-market.ru/mcp/"]
    }
  }
}
```

Restart Claude Desktop. The 24 tools appear under the MCP icon.

### Cursor, Windsurf, any Streamable-HTTP client

Point the client directly at `https://mcp-market.ru/mcp/` — no wrapper required.

### Python (`mcp` client)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("https://mcp-market.ru/mcp/") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("smart_match", {"brief": "каркасный дом 180 кв.м в Подмосковье до 15 млн"})
        print(result)
```

## Tools (24)

### Search & catalog

| Tool | Purpose |
| --- | --- |
| `search_companies` | Search 3 395 contractors by category / region / budget / free-text query |
| `search_projects` | Search 13 436 house projects by area, floors, material, price |
| `get_company` | Full company profile: contacts, prices, rating, reviews, projects |
| `get_project` | Project specs, pricing, features, company contacts |
| `get_categories` | All categories + company count per category |
| `get_regions` | All 18 regions + company count per region |
| `get_stats` | Catalog totals + daily agent-query / lead counters |
| `export_search_csv` | Export companies/projects search results as CSV (UTF-8 with BOM, Excel-friendly) |

### Analytics

| Tool | Purpose |
| --- | --- |
| `market_analytics` | Aggregate market view: segments, pricing bands, regional density |
| `market_report` | Narrative market report for a specified region |
| `trend_analyzer` | Company growth, price dynamics, rating changes over time |
| `price_comparison` | Prices across regions and categories side-by-side |
| `region_comparison` | Compare multiple regions on companies / projects / prices |
| `compare_companies` | Head-to-head comparison of 2–3 companies |

### Recommendation & estimation

| Tool | Purpose |
| --- | --- |
| `find_best_companies` | Rank contractors matching budget, region, rating floor |
| `contractor_recommendation` | AI-weighted top picks with reasoning |
| `smart_match` | Natural-language Russian brief → parsed filters + top-N contractors |
| `calculate_cost` | Quick cost estimate from category + region + area |
| `project_estimator` | Detailed estimate with economy / standard / premium tiers |

### Deep profiles

| Tool | Purpose |
| --- | --- |
| `company_portfolio` | Full portfolio: all projects, prices, reviews, contacts |
| `company_deep_profile` | Company profile plus reviews, categories, pricing history |
| `review_analysis` | Sentiment breakdown, themes, strengths & weaknesses |

### Lead generation

| Tool | Purpose |
| --- | --- |
| `request_quote` | Submit a lead; vendor notified via Telegram + email |
| `get_lead_status` | Check status of a previously-submitted lead (new / contacted / won / lost) |

## Pricing

| Tier | Limit | Tools |
| --- | --- | --- |
| **Free** | 100 req/day | Search + catalog tools |
| **Starter** | 1 000 req/day | + Analytics |
| **Pro** | 10 000 req/day | + Recommendations + Deep profiles |
| **Enterprise** | custom | Everything + dedicated support |

Get an API key: <https://mcp-market.ru/register>

## Data freshness

Data is refreshed weekly from public registries, vendor sites, and project portals. Coverage stats:

| Field | Fill rate |
| --- | --- |
| Description | 100 % |
| Rating | 94 % |
| Website | 62 % |
| Phone | 44 % |
| Email | 30 % |

Last refresh: **April 2026**.

## Architecture

- **FastAPI + FastMCP** over Streamable HTTP at `/mcp/`
- **PostgreSQL 16** for catalog & leads
- **Content-negotiated landing** at `/mcp/` — `text/html` returns docs, `text/event-stream` returns the MCP transport
- **TLS** via Let's Encrypt, hosted in Moscow datacenter

REST mirror available at `/api/v1/...` for non-MCP clients (see `/api/endpoints`).

## License

MIT — see [LICENSE](./LICENSE).

## Contact

- Site: <https://mcp-market.ru/>
- Issues: <https://github.com/devids77/mcp-market-ru/issues>
- Telegram: [@Devavatar](https://t.me/Devavatar)
