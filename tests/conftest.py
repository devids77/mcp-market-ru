"""Shared pytest fixtures for MCP Market integration tests.

Tests run against the live deployment by default (https://mcp-market.ru).
Set MCP_BASE_URL environment variable to override (e.g. http://localhost:8000).
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests


BASE_URL = os.environ.get("MCP_BASE_URL", "https://mcp-market.ru").rstrip("/")
MCP_ENDPOINT = f"{BASE_URL}/mcp/"
API_ENDPOINT = f"{BASE_URL}/api"
DEFAULT_TIMEOUT = 15


@pytest.fixture(scope="session")
def mcp_url() -> str:
    return MCP_ENDPOINT


@pytest.fixture(scope="session")
def api_url() -> str:
    return API_ENDPOINT


def _rpc(method: str, params: dict | None = None, request_id: str | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


@pytest.fixture(scope="session")
def mcp_session(mcp_url: str) -> dict:
    """Open an MCP session and return {session_id, protocol_version, headers}."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    init = _rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-market-tests", "version": "1.0"},
        },
    )
    r = requests.post(mcp_url, json=init, headers=headers, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    session_id = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
    assert session_id, f"initialize did not return session id (headers={dict(r.headers)})"
    proto = "2024-11-05"
    headers["mcp-session-id"] = session_id
    return {"session_id": session_id, "protocol_version": proto, "headers": headers}


@pytest.fixture()
def rpc():
    return _rpc
