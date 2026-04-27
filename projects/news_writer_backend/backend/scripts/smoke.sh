#!/usr/bin/env bash
# 端到端冒烟：health / auth / events / writing / drafts
# 使用：
#   AUTH_INITIAL_API_TOKEN=test-token-123 BASE=http://localhost:8000/api/v1 ./scripts/smoke.sh
set -euo pipefail

TOKEN="${AUTH_INITIAL_API_TOKEN:-test-token-123}"
BASE="${BASE:-http://localhost:8000/api/v1}"
AUTH="Authorization: Bearer $TOKEN"
JSON="Content-Type: application/json"

echo "# 1. health"
curl -sf "$BASE/health" | jq '{status, version, checks}'

echo "# 2. /auth/me"
curl -sf "$BASE/auth/me" -H "$AUTH" | jq '.user.id'

echo "# 3. 触发刷新（抓取 + 聚合）"
curl -sf -X POST "$BASE/events/refresh" -H "$AUTH" -H "$JSON" -d '{}' | jq '.'

echo "# 4. 列事件（若无事件可能为空）"
EV_JSON=$(curl -sf "$BASE/events?limit=1" -H "$AUTH")
EV_ID=$(echo "$EV_JSON" | jq -r '.items[0].id // empty')
if [[ -z "$EV_ID" ]]; then
  echo "!! 目前没有事件，跳过后续 writing/drafts 冒烟。先等一轮聚合完成再重跑。"
  exit 0
fi
echo "event_id=$EV_ID"

echo "# 5. 事件详情"
curl -sf "$BASE/events/$EV_ID" -H "$AUTH" | jq '{id, title, source_count}'

echo "# 6. generate-outline"
OUTLINE=$(curl -sf -X POST "$BASE/writing/generate-outline" -H "$AUTH" -H "$JSON" \
  -d "{\"event_id\":\"$EV_ID\",\"angle_type\":\"trend\"}")
echo "$OUTLINE" | jq '{titles: .title_candidates, sections: (.outline | length)}'

echo "# 7. 创建草稿"
# 简易 ULID（把系统时间转 base32，仅冒烟能用）
DRAFT_ID=$(python3 -c "from ulid import ULID; print(str(ULID()))" 2>/dev/null || uuidgen | tr -d - | head -c 26 | tr '[:lower:]' '[:upper:]')
TITLE=$(echo "$OUTLINE" | jq -r '.title_candidates[0]')
OUTLINE_ARR=$(echo "$OUTLINE" | jq '.outline')
curl -sf -X POST "$BASE/drafts" -H "$AUTH" -H "$JSON" \
  -d "$(jq -n --arg id "$DRAFT_ID" --arg eid "$EV_ID" --arg title "$TITLE" --argjson outline "$OUTLINE_ARR" '{id:$id, event_id:$eid, title:$title, angle_type:"trend", outline:$outline, content_markdown:""}')" \
  | jq '.draft.id'

echo "# 8. generate-section（lead）"
curl -sf -X POST "$BASE/writing/generate-section" -H "$AUTH" -H "$JSON" \
  -d "{\"draft_id\":\"$DRAFT_ID\",\"section_key\":\"lead\"}" | jq '{section_key, len: (.content_markdown | length)}'

echo "# 9. prepublish-check"
curl -sf -X POST "$BASE/writing/prepublish-check" -H "$AUTH" -H "$JSON" \
  -d "{\"draft_id\":\"$DRAFT_ID\"}" | jq '.issues'

echo "# SMOKE PASSED"
