#!/bin/bash
# Batch project enrichment for all regions (except LenObl - already done)
LOGDIR="/opt/mcp-market/logs"
mkdir -p "$LOGDIR"
SCRIPT="/opt/mcp-market/scripts/enrich_lenobl.py"

echo "=========================================="
echo "$(date) BATCH PROJECT ENRICHMENT START"
echo "=========================================="

for region in "Краснодарский край" "Московская область" "Тюменская область" \
  "Новосибирская область" "Красноярский край" "Свердловская область" \
  "Республика Башкортостан" "Республика Татарстан" "Самарская область" \
  "Воронежская область" "Челябинская область" "Ростовская область" \
  "Пермский край" "Волгоградская область" "Нижегородская область" \
  "Омская область" "Иркутская область"; do
  slug=$(echo "$region" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
  echo "=========================================="
  echo "$(date) STARTING: $region"
  echo "=========================================="
  python3 "$SCRIPT" "$region" > "$LOGDIR/${slug}_projects.log" 2>&1
  exit_code=$?
  echo "$(date) DONE: $region (exit: $exit_code)"
  grep "projects found\|COMPLETE\|companies processed\|ERROR" "$LOGDIR/${slug}_projects.log" | tail -5
  echo "$(date) REGION COMPLETE: $region"
done

echo "=========================================="
echo "$(date) ALL REGIONS PROJECT ENRICHMENT DONE"
echo "=========================================="

# Final stats
docker exec mcp-db psql -U mcpuser -d mcpmarket -c "
  SELECT COUNT(*) as total_projects FROM projects;
"
docker exec mcp-db psql -U mcpuser -d mcpmarket -c "
  SELECT COUNT(*) total, COUNT(NULLIF(projects_count,0)) with_projects,
    COUNT(phone) with_phone, COUNT(email) with_email,
    COUNT(price_per_sqm_min) with_price
  FROM companies;
"
