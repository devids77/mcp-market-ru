# MCP Market Russia 🏗️

**Каталог строительных компаний и недвижимости для AI-агентов**

The first business MCP server catalog for the Russian construction and real estate market. Search 1000+ companies, browse house projects, compare prices, and request quotes — all through AI agents via MCP protocol.

## 🔗 Connect

Add to your Claude Desktop, Cursor, or any MCP client:

```json
{
  "mcpServers": {
    "mcp-market": {
      "url": "https://mcp-market.ru/mcp"
    }
  }
}
```

## 🛠️ Available Tools

| Tool | Description |
|------|-------------|
| `search_companies` | Search construction companies by category, region, budget |
| `search_projects` | Find house projects by area, floors, material, price |
| `get_company` | Get full company details with all projects |
| `get_project` | Get detailed project info (specs, price, photos) |
| `get_categories` | List all company categories with counts |
| `get_regions` | List all regions with company counts |
| `get_stats` | Catalog statistics |
| `request_quote` | Send a quote request to a company |

## 💬 Example Prompts

- "Найди строительные компании каркасных домов в Московской области"
- "Покажи проекты домов из бруса 100-150 м² до 5 миллионов рублей"
- "Сравни цены на газобетонные дома в Ленинградской области"
- "Find construction companies in Moscow region with budget under 5M rubles"

## 📊 Data Sources

- Company data aggregated from public sources (2GIS, Avito, construction catalogs)
- Updated weekly
- Companies can claim and enhance their profiles

## 🏢 For Companies

Your company is already in our catalog? Claim your profile to:
- Update your information
- Add detailed project descriptions
- Receive leads from AI agents
- Get analytics on agent queries

## 📄 License

MIT

## 🔗 Links

- Server: https://mcp-market.ru/mcp
- Health: https://mcp-market.ru/health
- Stats: https://mcp-market.ru/stats
