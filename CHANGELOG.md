# Changelog

All notable changes to MCP Market Russia are documented here.
Versioning follows [SemVer](https://semver.org/).

## [3.2.0] - 2026-05-25

### Added
- `/api/v1/health` public endpoint (200 OK, free tier) for monitoring integrations (Glama, UptimeRobot)
- `/quickstart` and `/docs` HTML routes for agent onboarding
- `mcp_config_snippet`, `quickstart_url`, and `note` fields in `/api/register` response
- Russian-language stemmer (38 suffixes) and tag-priority OR clauses in `search_companies`
- `pytest` test suite covering MCP `initialize` / `tools/list` / `tools/call`, REST endpoints, classifier regex
- GitHub Actions CI workflow (pytest on push to master/main)
- SECURITY.md disclosure policy
- LICENSE (MIT)
- 24 MCP tools total: `export_search_csv`, `smart_match`, `get_lead_status` added in 3.1 line
- `FREE_TOOLS` constant exposes 11 tools to anonymous agents (incl. `smart_match` for onboarding)

### Fixed
- Telegram lead notifications: pinned `api.telegram.org` to `149.154.167.220` in `docker-compose.yml` (workaround for RU CDN block of `.166.110`)
- `dashboard_overview` cache-miss race: single-flight lock + `asyncio.to_thread` for sync DB calls
- `/api/v1/health` previously `401` -> now `200 OK` as free tier
- `request_quote` silent-except: exceptions now logged in `send_telegram_notification`
- Pricing/UI sync between `pricing.html`, `pay.html`, and API: 5 tools -> 21 (free), 9990 RUB -> 7990 (pro)

### Changed (Phase 3 classifier, 2026-04-28)
- AI re-classify all 3395 companies via GLM-4.6, average tags/company 1.5 -> 2
- Description cleanup: 101 Yellow Pages stubs backed up to `description_orig` and nulled
- Tags coverage on companies: 0% -> 67% (2275 companies)
- Smoke-test "каркасные дома в спб": 6 -> 11 hits (+83%)
- Repository cleanup: applied patch scripts moved to `scripts/legacy_patches/`

## [3.1.0] - 2026-04-20

### Added
- 24 MCP tools (was 21)
- `FREE_TOOLS = 11` constant including `smart_match` for anonymous-agent flows

## [3.0.0] - 2026-04-14

- Initial public release of the MCP server.
- 3 395 companies, 20 322 projects, 18 regions.
- 21 MCP tools (search, analytics, recommendation, deep profile, lead generation).
