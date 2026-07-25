#!/usr/bin/env bash
# Fail if production hasn't ingested events recently.
#
# The Daily Scrape stopping is otherwise silent — GET /events keeps serving the
# last successful ingest, so the site looks fine while quietly showing week-old
# data. That is exactly what happened in #244: GitHub disabled the scheduled
# workflow after 60 days of repo inactivity and nothing surfaced it.
#
# Env:
#   HEALTH_URL     health endpoint to poll (required)
#   MAX_AGE_HOURS  fail above this ingest age (default 48)
set -euo pipefail

HEALTH_URL="${HEALTH_URL:?HEALTH_URL is required}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-48}"

# fly.toml runs with min_machines_running = 0, so the first request can time out
# while the machine cold-starts. Retry before concluding anything is wrong.
response=""
for attempt in 1 2 3 4 5; do
  if response=$(curl -fsS --max-time 30 "$HEALTH_URL" 2>/dev/null); then
    break
  fi
  echo "attempt $attempt: $HEALTH_URL not reachable yet, retrying..."
  response=""
  sleep 10
done

if [ -z "$response" ]; then
  echo "FAIL: $HEALTH_URL unreachable after 5 attempts."
  exit 1
fi

echo "$response"

database=$(echo "$response" | jq -r '.database // "missing"')
if [ "$database" != "ok" ]; then
  echo "FAIL: health reports database=$database"
  exit 1
fi

age=$(echo "$response" | jq -r '.hours_since_ingest // "null"')
if [ "$age" = "null" ]; then
  echo "FAIL: health reports no ingest has ever run (last_ingest_at is null)."
  exit 1
fi

# jq handles the float comparison; bash can't compare decimals.
if [ "$(jq -n --argjson a "$age" --argjson m "$MAX_AGE_HOURS" '$a > $m')" = "true" ]; then
  cat <<EOF
FAIL: production last ingested ${age}h ago, over the ${MAX_AGE_HOURS}h threshold.

The Daily Scrape has probably stopped. Check whether GitHub disabled it:

  gh api repos/linuxmaier/whats-up-madison/actions/workflows \\
    --jq '.workflows[] | .name + "  " + .state'

A state of 'disabled_inactivity' means it was auto-disabled after 60 days of
repo inactivity. Re-enable and kick off a run:

  gh api -X PUT repos/linuxmaier/whats-up-madison/actions/workflows/<id>/enable
  gh workflow run scrape.yml
EOF
  exit 1
fi

echo "OK: production last ingested ${age}h ago (threshold ${MAX_AGE_HOURS}h)."
