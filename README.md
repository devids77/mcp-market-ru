# MCP Market Russia 🏗️

**MCP server for the Russian construction and real estate market.** Search 3,395 construction companies, browse 4,468 house projects, compare prices, request quotes — all via the [Model Context Protocol](https://modelcontextprotocol.io) or REST API.

[![Live](https://img.shields.io/badge/live-mcp--market.ru-blue)](https://mcp-market.ru)
[![Stats](https://img.shields.io/badge/companies-3395-green)](https://mcp-market.ru/dashboard)
[![Projects](https://img.shields.io/badge/projects-4468-green)](https://mcp-market.ru/dashboard)
[![License](https://img.shields.io/badge/license-MIT-blue)](#license)

Listed in the [official MCP Registry](https://registry.modelcontextprotocol.io) as `io.github.devids77/mcp-market-ru`.

## What this is

A live, hosted MCP server that gives AI agents (Claude Desktop, Cursor, Cline, Continue, etc.) direct access to a curated catalog of Russian construction companies and home-building projects, complete with pricing, ratings, regions, photos and contact info aggregated from public sources.

No registration needed for the basic catalog — point your MCP client at `https://mcp-market.ru/mcp` and start asking questions.

## Quick start — Claude Desktop

Open your Claude Desktop config:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json

Add:

```json
{
  "mcpServers": {
    "mcp-market": {
      "url": "https://mcp-market.ru/mcp"
    }
  }
}
```

Restart Claude Desktop. The 24 tools are now available — Claude will call them automatically when you ask construction-related questions.

## Quick start — Cursor

Settings → MCP → Add new MCP server. URL: `https://mcp-market.ru/mcp`

## Quick start — REST API

Free tier works without an API key:

```bash
# Search companies
curl "https://mcp-market.ru/api/v1/search/companies?q=каркасные+дома+в+спб"

# Get a specific company
curl "https://mcp-market.ru/api/v1/companies/<company_id>"

# Search projects by area and budget
curl "https://mcp-market.ru/api/v1/search/projects?q=брус+150&min_price=3000000"

# Catalog stats
curl "https://mcp-market.ru/api/dashboard/stats"
```

Paid tiers (Analytics, AI Tools) require an API key — pass it as `X-API-Key` header or `?api_key=` query param.

## What you can ask

Example prompts that work well with the MCP server:

- "Find frame houses (каркасные дома) in Moscow region under 12 million rubles"
- "Compare timber (брус) projects between 120-150 m²"
- "Show top-10 companies in Krasnodar region by rating"
- "Send a quote request to company X with my contact details"
- "What's the average price per m² for monolith houses in St Petersburg?"

The server supports both Russian and English queries with proper synonym handling for Russian regions (`спб` → Saint Petersburg, `мск` → Moscow, etc.) and construction terminology.

## Available tools

| Tool | Tier | Description |
|------|------|-------------|
| `search_companies` | Free | Search construction companies by category, region, budget, tags |
| `search_projects` | Free | Search house projects by area, price, material |
| `get_company` | Free | Full company details with all projects |
| `get_project` | Free | Complete project card (specs, price, photos) |
| `get_categories` | Free | List all company categories with counts |
| `get_regions` | Free | List all regions with company counts |
| `get_stats` | Free | Catalog statistics |
| `smart_match` | Free | Match companies to budget + region + category |
| `request_quote` | Free | Send a lead/quote request to a company |
| `compare` | Free | Compare multiple companies side-by-side |
| `calculate` | Free | Project cost estimator |
| `analytics/market` | Starter | Regional market analytics |
| `analytics/best-companies` | Starter | Top companies with extended metrics |
| `analytics/price-comparison` | Starter | Price comparison across segments |
| `analytics/report` | Starter | Full analytical report |
| `ai/recommend` | Pro | AI recommendations for client criteria |
| `ai/estimate` | Pro | AI cost estimate from project description |
| `ai/reviews` | Pro | AI-summarized reviews per company |
| `ai/trends` | Pro | AI market trend analysis |
| `ai/deep-profile` | Pro | Deep company profile with insights |
| `ai/region-compare` | Pro | AI comparison of regions |

## Pricing

| Plan | Price | Requests/day | Tools |
|------|-------|--------------|-------|
| Free | ₽0 | 100 | 21 (all Free-tier tools) |
| Starter | ₽2 990/mo | 1 000 | 21 + Analytics |
| Pro | ₽7 990/mo | 5 000 | 21 + Analytics + AI Tools |
| Enterprise | ₽24 990/mo | unlimited | 21 + custom, SLA, white-label |

Get a key at [https://mcp-market.ru/pricing](https://mcp-market.ru/pricing).

## Data

- **3,395 companies** aggregated from public sources (2GIS, Avito, construction catalogs, Yandex)
- **4,468 projects** with specs, materials, area, price, photos
- **18 regions** covered (Moscow, St Petersburg, Krasnodar, Yekaterinburg, …)
- **67% tagged** via regex + GLM-4.6 classifier — search by tag works for queries like "bath house in Krasnodar"
- **Live data:** companies and projects refreshed periodically; check [`/dashboard`](https://mcp-market.ru/dashboard) for current counts

## For construction companies

Your company is already in the catalog? Claim your profile to:
- Edit your description, photos, and contact info
- Add detailed project portfolios
- Receive leads from AI agents directly to your inbox + Telegram
- Get analytics on which AI queries reached your card

Email **info@mcp-market.ru** to claim.

## Architecture

- **FastAPI** + **FastMCP** for HTTP + MCP transport layered on the same `/mcp/` endpoint
- **PostgreSQL 16** with full-text + GIN-indexed tag array
- **Docker Compose** deployment
- **Nginx** + Let's Encrypt for HTTPS termination
- **Single-flight cache** on heavy endpoints (`dashboard/overview` is 30s)

## Links

- Live site: [https://mcp-market.ru](https://mcp-market.ru)
- Demo (smart_match without registration): [/demo](https://mcp-market.ru/demo)
- Live dashboard: [/dashboard](https://mcp-market.ru/dashboard)
- Pricing: [/pricing](https://mcp-market.ru/pricing)
- Quickstart docs: [/quickstart](https://mcp-market.ru/quickstart)
- MCP endpoint: `https://mcp-market.ru/mcp`
- Contact: **info@mcp-market.ru**

## Error codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 400 | Bad request parameters |
| 401 | API key required for this endpoint |
| 403 | Your plan doesn't cover this endpoint |
| 404 | Not found |
| 429 | Daily request limit exceeded |
| 500 | Server error — report to info@mcp-market.ru |

## License

MIT
