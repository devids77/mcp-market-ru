#!/bin/bash
# MCP Market — Deploy Script
# Run on server: bash deploy.sh

set -e

echo "=== MCP Market Deploy ==="
echo ""

PROJECT_DIR="/opt/mcp-market"

# 1. Create project directory
echo "[1/6] Creating project directory..."
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# 2. Copy .env
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  → .env created (edit if needed)"
else
    echo "  → .env already exists, skipping"
fi

# 3. Build and start containers
echo "[2/6] Building Docker containers..."
docker compose build --no-cache

echo "[3/6] Starting containers..."
docker compose up -d

# 4. Wait for DB to be ready
echo "[4/6] Waiting for database..."
sleep 5
until docker compose exec -T db pg_isready -U mcpuser -d mcpmarket 2>/dev/null; do
    echo "  → Waiting for PostgreSQL..."
    sleep 2
done
echo "  → Database is ready!"

# 5. Setup Nginx
echo "[5/6] Configuring Nginx..."
cp -f nginx/conf.d/mcp-market.conf /etc/nginx/sites-available/mcp-market.conf
ln -sf /etc/nginx/sites-available/mcp-market.conf /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "  → Nginx configured!"

# 6. Verify
echo "[6/6] Verifying..."
sleep 2

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health)
if [ "$HTTP_CODE" = "200" ]; then
    echo ""
    echo "=== SUCCESS ==="
    echo "MCP Server: http://localhost:8000"
    echo "Health:     http://localhost:8000/health"
    echo "MCP:        http://localhost:8000/mcp"
    echo "Docs:       http://localhost:8000/docs"
    echo ""
    echo "External:   https://mcp-market.ru (after DNS setup)"
    echo ""
    STATS=$(curl -s http://localhost:8000/stats)
    echo "Stats: $STATS"
else
    echo ""
    echo "=== WARNING ==="
    echo "Server returned HTTP $HTTP_CODE"
    echo "Check logs: docker compose logs mcp-server"
fi
