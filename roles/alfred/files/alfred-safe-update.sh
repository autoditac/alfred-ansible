#!/bin/bash
# alfred-safe-update — only run podman auto-update when the mower is
# docked/idle and no CaSSAndRA schedule starts within BUFFER_MIN minutes.
set -euo pipefail

DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000/api/status}"
SCHEDULE_FILE="${SCHEDULE_FILE:-/home/pi/.cassandra/user/schedulecfg.json}"
BUFFER_MIN="${BUFFER_MIN:-30}"

log() { echo "$(date '+%F %T') alfred-safe-update: $*"; }

# --- 1. Check mower state via dashboard API ---
status_json=$(curl -sf --max-time 5 "$DASHBOARD_URL" 2>/dev/null) || {
    log "SKIP — dashboard unreachable (mower may be off)"
    exit 0
}

operation=$(echo "$status_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('operation', -1))" 2>/dev/null) || operation=-1
op_name=$(echo "$status_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('operationName', 'UNKNOWN'))" 2>/dev/null) || op_name="UNKNOWN"

# 0=IDLE, 1=MOW, 2=CHARGE, 3=ERROR, 4=DOCK
if [[ "$operation" == "1" || "$operation" == "4" ]]; then
    log "SKIP — mower is $op_name (op=$operation)"
    exit 0
fi

log "Mower state OK: $op_name (op=$operation)"

# --- 2. Check CaSSAndRA schedule ---
if [[ -f "$SCHEDULE_FILE" ]]; then
    schedule_check=$(python3 -c "
import json, sys
from datetime import datetime

with open('$SCHEDULE_FILE') as f:
    cfg = json.load(f)

if not cfg.get('use_schedule', False):
    print('inactive')
    sys.exit(0)

days = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
today = days[datetime.now().weekday()]

time_range = None
for entry in cfg.get('time_range', []):
    if today in entry:
        time_range = entry[today]
        break

if not time_range or (time_range[1] - time_range[0] == 0):
    print('no_schedule_today')
    sys.exit(0)

start_hour = time_range[0]
start_minutes = int(start_hour) * 60 + int((start_hour % 1) * 60)
now = datetime.now()
now_minutes = now.hour * 60 + now.minute
diff = start_minutes - now_minutes

if 0 <= diff <= $BUFFER_MIN:
    print(f'starts_soon:{diff}')
else:
    print('safe')
" 2>/dev/null) || schedule_check="error"

    case "$schedule_check" in
        inactive|no_schedule_today|safe)
            log "Schedule check: $schedule_check"
            ;;
        starts_soon:*)
            minutes_left="${schedule_check#starts_soon:}"
            log "SKIP — schedule starts in ${minutes_left} min (buffer=${BUFFER_MIN}m)"
            exit 0
            ;;
        error)
            log "WARN — could not read schedule, proceeding anyway"
            ;;
    esac
else
    log "No schedule file found, proceeding"
fi

# --- 3. Run the update ---
# Pre-pull images to refresh the local manifest reference. podman auto-update
# compares the manifest digest of the running container against the registry;
# GHCR's CDN caches manifests briefly (~1–5 min), which can cause auto-update
# to see a stale digest and skip a freshly published image. An explicit pull
# bypasses that cache-miss window.
log "Pre-pulling images to refresh manifest cache"
for img in ghcr.io/autoditac/sunray:alpha \
           ghcr.io/autoditac/cassandra:latest \
           ghcr.io/autoditac/alfred-dashboard:alpha; do
    podman pull --quiet "$img" 2>&1 | while IFS= read -r line; do log "pull $img: $line"; done \
        || log "WARN — pull $img failed"
done

log "Running podman auto-update"
podman auto-update 2>&1 | while IFS= read -r line; do log "$line"; done
log "Done"
