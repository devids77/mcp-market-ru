#!/bin/bash
# Batch enrichment: 2GIS + Yandex for all regions
# Usage: nohup bash /opt/mcp-market/scripts/enrich_all_regions.sh > /opt/mcp-market/enrich_all.log 2>&1 &

LOGDIR="/opt/mcp-market/logs"
mkdir -p "$LOGDIR"

REGIONS=(
  "Краснодарский край"
  "Московская область"
  "Тюменская область"
  "Новосибирская область"
  "Красноярский край"
  "Свердловская область"
  "Республика Башкортостан"
  "Республика Татарстан"
  "Самарская область"
  "Воронежская область"
  "Челябинская область"
  "Ростовская область"
  "Пермский край"
  "Волгоградская область"
  "Нижегородская область"
  "Омская область"
  "Иркутская область"
)

SCRIPTS_DIR="/opt/mcp-market/scripts"

for region in "${REGIONS[@]}"; do
  slug=$(echo "$region" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
  echo "=========================================="
  echo "$(date) STARTING REGION: $region"
  echo "=========================================="

  # 2GIS
  echo "$(date) Running 2GIS for $region..."
  python3 "$SCRIPTS_DIR/enrich_ratings_playwright.py" "$region" > "$LOGDIR/${slug}_2gis.log" 2>&1
  echo "$(date) 2GIS DONE for $region (exit code: $?)"
  tail -5 "$LOGDIR/${slug}_2gis.log"

  # Yandex (picks up companies still without ratings)
  echo "$(date) Running Yandex for $region..."
  python3 "$SCRIPTS_DIR/enrich_ratings_yandex.py" "$region" > "$LOGDIR/${slug}_yandex.log" 2>&1
  echo "$(date) Yandex DONE for $region (exit code: $?)"
  tail -5 "$LOGDIR/${slug}_yandex.log"

  echo "$(date) REGION COMPLETE: $region"
  echo ""
done

echo "=========================================="
echo "$(date) ALL REGIONS COMPLETE"
echo "=========================================="

# Summary
echo ""
echo "=== FINAL DB STATS ==="
docker exec mcp-db psql -U mcpuser -d mcpmarket -c "
SELECT region, COUNT(*) as total,
  SUM(CASE WHEN rating IS NOT NULL AND rating > 0 THEN 1 ELSE 0 END) as with_rating,
  ROUND(AVG(CASE WHEN rating > 0 THEN rating END)::numeric, 2) as avg_rating
FROM companies GROUP BY region ORDER BY total DESC;
"
