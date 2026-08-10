# Dockerfile - stdio <-> Streamable-HTTP bridge for MCP Market Russia.
#
# MCP Market Russia is a HOSTED MCP server: the live endpoint is
# https://mcp-market.ru/mcp/ and needs no build, no database and no API key.
# You do not need this image to use it - just point your client at that URL
# (see README / https://mcp-market.ru/quickstart).
#
# This image exists for callers that can only launch a local stdio process:
#   1. MCP catalogs that introspect a server by building its image and then
#      speaking `initialize` + `tools/list` over stdio (e.g. Glama).
#   2. Clients without remote-server support.
# The bridge relays stdio JSON-RPC to the hosted endpoint, so the real, live
# tool list is what the caller sees.
#
# The production API image is built from Dockerfile.prod (see docker-compose.yml).
#
#   docker build -t mcp-market-bridge .
#   docker run -i --rm mcp-market-bridge

FROM node:20-alpine

# Hosted endpoint the bridge proxies to. Override to target another instance.
ENV MCP_MARKET_URL=https://mcp-market.ru/mcp/

WORKDIR /app

# The bridge has zero dependencies (native fetch + node:readline), so there is
# no install step - copying the entrypoint is enough.
COPY bin/mcp-market-bridge.js ./bin/

# stdio MCP server: reads JSON-RPC on stdin, writes responses on stdout.
ENTRYPOINT ["node", "bin/mcp-market-bridge.js"]
