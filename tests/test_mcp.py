"""Smoke tests for the MCP HTTP transport (FastMCP)."""
from __future__ import annotations

import json

import pytest
import requests

pytestmark = pytest.mark.integration


def _post(url, payload, headers, timeout=30):
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    r.encoding = "utf-8"
    r.raise_for_status()
    return r


def _parse(r):
    """FastMCP returns text/event-stream; concatenate data: lines as one JSON."""
    ctype = r.headers.get("content-type", "")
    if "event-stream" not in ctype:
        return r.json()
    chunks = []
    for line in r.text.splitlines():
        if line.startswith("data:"):
            chunks.append(line[5:].lstrip())
    if not chunks:
        raise AssertionError("no SSE data lines in response")
    return json.loads("".join(chunks))


def test_initialize_returns_session(mcp_session):
    assert mcp_session["session_id"]
    assert mcp_session["protocol_version"] == "2024-11-05"


def test_tools_list_minimum_count(mcp_url, mcp_session, rpc):
    body = _parse(_post(mcp_url, rpc("tools/list"), mcp_session["headers"]))
    tools = body.get("result", {}).get("tools", [])
    assert isinstance(tools, list)
    assert len(tools) >= 20, "expected >=20 MCP tools, got " + str(len(tools))


def test_tools_list_contains_core(mcp_url, mcp_session, rpc):
    body = _parse(_post(mcp_url, rpc("tools/list"), mcp_session["headers"]))
    names = {t["name"] for t in body.get("result", {}).get("tools", [])}
    for required in ("search_companies", "get_stats", "request_quote", "smart_match"):
        assert required in names, "core tool missing: " + required


def test_get_stats_returns_company_count(mcp_url, mcp_session, rpc):
    payload = rpc("tools/call", {"name": "get_stats", "arguments": {}})
    body = _parse(_post(mcp_url, payload, mcp_session["headers"]))
    assert "compan" in json.dumps(body).lower()
