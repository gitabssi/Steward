#!/usr/bin/env bash
# Replay one shift from the top — for a second take, or for a judge who
# wants to watch the arc without waiting for a real night to pass.
#
#   scripts/replay.sh            # ~6 min: every beat, agents have room to think
#   scripts/replay.sh fast       # ~2 min: beats land quickly; workers may fall
#                                #         back to their deterministic lines
#   scripts/replay.sh real       # 1 plant-minute per minute, as it would run
#
# The clock is the only thing that changes. The world, the permit limits
# and the agents' reasoning are identical in all three.
set -euo pipefail

cd "$(dirname "$0")/.."

case "${1:-demo}" in
  fast) RATE=0.9 ;;
  real) RATE=0.0167 ;;
  *)    RATE=0.25 ;;
esac

# The fleet's learned facts persist between shifts by design; a replay
# starts the operator's night over, so clear the local store.
rm -f "${STEWARD_MEMORY_PATH:-/tmp/steward-memory.json}"

echo "→ state primacy agency (the second publisher) on :8091"
uv run --no-project --with fastapi,uvicorn \
  uvicorn server:app --app-dir primacy --port 8091 >/dev/null 2>&1 &
PRIMACY=$!
trap 'kill $PRIMACY 2>/dev/null || true' EXIT
sleep 2

echo "→ console  http://localhost:8000/console/"
echo "→ ledger   http://localhost:8000/api/events"
echo "→ clock    ${RATE} plant-minutes per second"

PRIMACY_AGENCY_ENDPOINT=http://localhost:8091 \
STEWARD_FAULT_INJECTION=stale_lab_context \
STEWARD_CLOCK_RATE="$RATE" \
  uv run uvicorn app.fast_api_app:app --port 8000
