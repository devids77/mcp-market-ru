"""Smoke tests for the REST API (live deployment)."""
from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.integration


def test_health(api_url):
    r = requests.get(f"{api_url}/v1/health", timeout=10)
    assert r.status_code == 200, f"health endpoint must be 200, got {r.status_code}"
    body = r.json()
    assert body.get("status") == "ok", body


def test_search_companies_returns_results(api_url):
    r = requests.get(
        f"{api_url}/v1/search/companies",
        params={"q": "каркас", "limit": 3},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    items = body.get("results") or body.get("companies") or body.get("items") or []
    assert items, f"search for 'karkas' must return results, got {body}"


def test_dashboard_stats_shape(api_url):
    r = requests.get(f"{api_url}/dashboard/stats", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert any(
        k in body for k in ("companies", "total", "companies_total", "company_count")
    ), f"dashboard stats should expose company count: keys={list(body.keys())[:10]}"


def test_landing_serves_html(api_url):
    base = api_url.rsplit("/api", 1)[0]
    r = requests.get(base + "/", timeout=10)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "MCP" in r.text or "mcp" in r.text.lower()
