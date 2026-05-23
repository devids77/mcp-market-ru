#!/bin/bash
# Batch enrichment starting from Krasnodar Yandex (2GIS already done/running)
# Then all other regions with both 2GIS + Yandex
# Usage: nohup bash /opt/mcp-market/scripts/enrich_remaining.sh > /opt/mcp-market/enrich_all.log 2>&1 &

LOGDIR="/opt/mcp-market/logs"
mkdir -p "$LOGDIR"
SCRIPTS_DIR="/opt/mcp-market/scripts"

run_region() {
  local region="$1"
  local skip_2gis="$2"
  local slug=$(echo "$region" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
  
  echo "=========================================="
  echo "$(date) STARTING REGION: $region"
  echo "=========================================="

  if [ "$skip_2gis" != "skip" ]; then
    echo "$(date) Running 2GIS for $region..."
    python3 "$SCRIPTS_DIR/enrich_ratings_playwright.py" "$region" > "$LOGDIR/${slug}_2gis.log" 2>&1
    echo "$(date) 2GIS DONE for $region (exit: $?)"
    grep "COMPLETE\|PROGRESS" "$LOGDIR/${slug}_2gis.log" | tail -3
  else
    echo "$(date) SKIPPING 2GIS for $region (already done)"
  fi

  echo "$(date) Running Yandex for $region..."
  python3 "$SCRIPTS_DIR/enrich_ratings_yandex.py" "$region" > "$LOGDIR/${slug}_yandex.log" 2>&1
  echo "$(date) Yandex DONE for $region (exit: $?)"
  grep "COMPLETE\|PROGRESS" "$LOGDIR/${slug}_yandex.log" | tail -3

  echo "$(date) REGION COMPLETE: $region"
  echo ""
}

# Wait for any running 2GIS Krasnodar process
echo "Checking for running 2GIS Krasnodar process..."
while pgrep -f "enrich_ratings_playwright.*Краснодарский" > /dev/null 2>&1; do
  echo "$(date) Waiting for 2GIS Krasnodar to finish..."
  sleep 60
done
echo "$(date) 2GIS Krasnodar finished or not running."

# Krasnodar: only Yandex (2GIS already done)
run_region "Краснодарский край" "skip"

# All other regions: both 2GIS + Yandex
for region in \
  "Московская область" \
  "Тюменская область" \
  "Новосибирская область" \
  "Красноярский край" \
  "Свердловская область" \
  "Республика Башкортостан" \
  "Республика Татарстан" \
  "Самарская область" \
  "Воронежская область" \
  "Челябинская область" \
  "Ростовская область" \
  "Пермский край" \
  "Волгоградская область" \
  "Нижегородская область" \
  "Омская область" \
  "Иркутская область"; do
  run_region "$region"
done

echo "=========================================="
echo "$(date) ALL REGIONS COMPLETE"
echo "=========================================="

echo ""
echo "=== FINAL DB STATS ==="
docker exec mcp-db psql -U mcpuser -d mcpmarket -c "
SELECT region, COUNT(*) as total,
  SUM(CASE WHEN rating IS NOT NULL AND rating > 0 THEN 1 ELSE 0 END) as with_rating,
  ROUND(100.0 * SUM(CASE WHEN rating IS NOT NULL AND rating > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct,
  ROUND(AVG(CASE WHEN rating > 0 THEN rating END)::numeric, 2) as avg_rating
FROM companies GROUP BY region ORDER BY total DESC;
"
