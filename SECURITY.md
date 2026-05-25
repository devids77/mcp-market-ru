# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in MCP Market Russia, please report it privately.

**Email:** scandiecodom@gmail.com

Include in your report:
- A clear description of the issue
- Steps to reproduce
- Potential impact and proposed severity
- Affected endpoint or version (if known)

We aim to acknowledge within 48 hours and provide a fix or mitigation within 14 days for confirmed vulnerabilities. Please do not open a public GitHub issue for security reports.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 3.2.x   | Yes       |
| 3.1.x   | Yes       |
| < 3.1   | No        |

## Scope

In scope:
- The MCP server at https://mcp-market.ru/mcp/
- The REST API at https://mcp-market.ru/api/
- The hosted code at https://github.com/devids77/mcp-market-ru

Out of scope:
- Social engineering of the maintainer
- Physical attacks on the VPS infrastructure
- Volume-based DoS attacks
- Findings in third-party dependencies without a working proof of concept

## Disclosure Policy

We practice coordinated disclosure. After a fix is deployed, we publish a security advisory with credit to the reporter (if requested). For high-severity issues we may delay disclosure up to 90 days.
