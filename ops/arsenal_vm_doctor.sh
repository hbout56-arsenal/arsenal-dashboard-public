#!/usr/bin/env bash
#
# arsenal_vm_doctor.sh — one-shot health check for the Arsenal feed VM.
#
# Runs on the macOS host that owns the Parallels VM. Bundles the manual
# runbook (prlctl / nc / launchctl / log tail) plus a dashboard-staleness
# check into a single command that prints one PASS / WARN / FAIL verdict.
#
# It is READ-ONLY by default. It never starts, stops, or mutates the VM
# unless you pass --start (which only boots a stopped VM).
#
# Usage:
#   ops/arsenal_vm_doctor.sh              # diagnose, change nothing
#   ops/arsenal_vm_doctor.sh --start      # also boot the VM if it is stopped
#   ops/arsenal_vm_doctor.sh --tail 100   # tail more log lines
#   ops/arsenal_vm_doctor.sh --help
#
# Override any default with an env var, e.g.:
#   VM_NAME="Arsenal" VM_PORT=5009 ops/arsenal_vm_doctor.sh
#
set -u

# ---------------------------------------------------------------------------
# Config (env-overridable; defaults mirror the runbook)
# ---------------------------------------------------------------------------
VM_NAME="${VM_NAME:-}"                       # empty => auto-detect (matches /arsenal/i)
VM_HOST="${VM_HOST:-10.211.55.3}"            # Parallels guest IP
VM_PORT="${VM_PORT:-5009}"                   # internals/IQFeed bridge port on the guest
LOG_GLOB="${LOG_GLOB:-$HOME/arsenal/logs/internals_live*.log}"
STARTUP_WAIT="${STARTUP_WAIT:-60}"           # seconds to wait after boot (IQConnect auto-login)
MAX_AGE_MIN="${MAX_AGE_MIN:-15}"             # dashboard snapshot older than this => STALE
TAIL_LINES="${TAIL_LINES:-50}"
DO_START=0

# Default snapshot = the repo copy next to this script (../internals_snapshot.json)
_SELF="${BASH_SOURCE[0]}"
_SCRIPT_DIR="$(cd "$(dirname "$_SELF")" && pwd)"
SNAPSHOT="${SNAPSHOT:-$_SCRIPT_DIR/../internals_snapshot.json}"

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --start)   DO_START=1 ;;
    --tail)    shift; TAIL_LINES="${1:-50}" ;;
    --tail=*)  TAIL_LINES="${1#*=}" ;;
    -h|--help)
      sed -n '2,30p' "$_SELF" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown arg: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_DIM=""; C_RST=""
fi

WORST=0   # 0 ok, 1 warn, 2 fail
_bump() { [ "$1" -gt "$WORST" ] && WORST="$1"; return 0; }

pass() { printf '  %sPASS%s %s\n'  "$C_GRN" "$C_RST" "$1"; }
warn() { printf '  %sWARN%s %s\n'  "$C_YEL" "$C_RST" "$1"; _bump 1; }
fail() { printf '  %sFAIL%s %s\n'  "$C_RED" "$C_RST" "$1"; _bump 2; }
info() { printf '  %s·%s    %s\n'  "$C_DIM" "$C_RST" "$1"; }
head2(){ printf '\n%s== %s ==%s\n' "$C_DIM" "$1" "$C_RST"; }

have() { command -v "$1" >/dev/null 2>&1; }

# Parse an ISO-8601 timestamp (with or without ":" in the tz offset) to epoch.
# Works with BSD (macOS) `date`. Echoes epoch on stdout, or nothing on failure.
iso_to_epoch() {
  local s="$1"
  # normalise "-04:00" -> "-0400" and a trailing "Z" -> "+0000"
  s="$(printf '%s' "$s" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/; s/Z$/+0000/')"
  if date -j -f "%Y-%m-%dT%H:%M:%S%z" "$s" +%s 2>/dev/null; then return 0; fi
  # fallback: no tz in string -> assume local
  date -j -f "%Y-%m-%dT%H:%M:%S" "${s%%[+-][0-9][0-9][0-9][0-9]}" +%s 2>/dev/null
}

human_age() {  # seconds -> "2h 5m" / "3d 4h"
  local s="$1" d h m
  d=$(( s / 86400 )); s=$(( s % 86400 ))
  h=$(( s / 3600 ));  m=$(( (s % 3600) / 60 ))
  if [ "$d" -gt 0 ]; then printf '%dd %dh' "$d" "$h"
  elif [ "$h" -gt 0 ]; then printf '%dh %dm' "$h" "$m"
  else printf '%dm' "$m"; fi
}

NOW=$(date +%s)
printf '%sArsenal VM doctor%s — %s\n' "$C_DIM" "$C_RST" "$(date '+%Y-%m-%d %H:%M:%S %Z')"

# ---------------------------------------------------------------------------
# 1. VM state (prlctl)
# ---------------------------------------------------------------------------
head2 "1. Parallels VM"
if ! have prlctl; then
  warn "prlctl not found — is this the macOS host with Parallels installed?"
else
  # Auto-detect VM name if not given.
  if [ -z "$VM_NAME" ]; then
    VM_NAME="$(prlctl list -a 2>/dev/null | awk 'NR>1{ $1=$2=$3=""; sub(/^ +/,""); print }' \
                | grep -i arsenal | head -1)"
  fi
  if [ -z "$VM_NAME" ]; then
    warn "could not auto-detect an 'arsenal' VM. Set VM_NAME=... explicitly."
    info "VMs seen:"; prlctl list -a 2>/dev/null | sed 's/^/      /'
  else
    VM_STATE="$(prlctl status "$VM_NAME" 2>/dev/null | awk '{print $NF}')"
    if [ -z "$VM_STATE" ]; then
      fail "VM '$VM_NAME' not found by prlctl status."
    elif [ "$VM_STATE" = "running" ]; then
      pass "VM '$VM_NAME' is running."
    else
      fail "VM '$VM_NAME' is $VM_STATE (not running)."
      if [ "$DO_START" -eq 1 ]; then
        info "Starting '$VM_NAME' (--start given)…"
        if prlctl start "$VM_NAME"; then
          info "Waiting ${STARTUP_WAIT}s for IQConnect auto-login…"
          sleep "$STARTUP_WAIT"
          VM_STATE="$(prlctl status "$VM_NAME" 2>/dev/null | awk '{print $NF}')"
          [ "$VM_STATE" = "running" ] && pass "VM is now running." || fail "VM still $VM_STATE after start."
        else
          fail "prlctl start failed."
        fi
      else
        info "Re-run with --start to boot it, or: prlctl start \"$VM_NAME\""
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 2. Guest port reachability (nc)
# ---------------------------------------------------------------------------
head2 "2. Feed port ${VM_HOST}:${VM_PORT}"
if ! have nc; then
  warn "nc not found — cannot test the port."
elif nc -z -w 3 "$VM_HOST" "$VM_PORT" >/dev/null 2>&1; then
  pass "port ${VM_PORT} open on ${VM_HOST} (feed bridge reachable)."
else
  fail "port ${VM_PORT} closed/unreachable on ${VM_HOST}."
  info "The feed process on the guest is likely down even if the VM is up."
fi

# ---------------------------------------------------------------------------
# 3. launchd agents (launchctl)
# ---------------------------------------------------------------------------
head2 "3. launchd agents (arsenal)"
if ! have launchctl; then
  warn "launchctl not found."
else
  LC_ROWS="$(launchctl list 2>/dev/null | grep -i arsenal)"
  if [ -z "$LC_ROWS" ]; then
    warn "no launchd jobs matching 'arsenal' are loaded."
    info "Nothing is scheduled to push the feed. Check ~/Library/LaunchAgents."
  else
    # columns: PID  STATUS  LABEL
    printf '%s\n' "$LC_ROWS" | while IFS= read -r row; do
      _pid="$(printf '%s' "$row"   | awk '{print $1}')"
      _stat="$(printf '%s' "$row"  | awk '{print $2}')"
      _label="$(printf '%s' "$row" | awk '{print $3}')"
      if [ "$_pid" != "-" ] && [ "$_pid" -eq "$_pid" ] 2>/dev/null; then
        printf '  %sPASS%s %s running (pid %s)\n' "$C_GRN" "$C_RST" "$_label" "$_pid"
      elif [ "$_stat" = "0" ]; then
        printf '  %s·%s    %s loaded, last exit 0 (idle/one-shot ok)\n' "$C_DIM" "$C_RST" "$_label"
      else
        printf '  %sWARN%s %s not running, last exit %s\n' "$C_YEL" "$C_RST" "$_label" "$_stat"
      fi
    done
    # A non-zero last-exit anywhere is worth a WARN on the overall verdict.
    printf '%s\n' "$LC_ROWS" | awk '{print $2}' | grep -Eqv '^(0|-)$' && _bump 1
  fi
fi

# ---------------------------------------------------------------------------
# 4. internals_live log
# ---------------------------------------------------------------------------
head2 "4. internals log"
LOG_FILE="$(ls -t $LOG_GLOB 2>/dev/null | head -1)"
if [ -z "$LOG_FILE" ]; then
  warn "no log file matches: $LOG_GLOB"
else
  # mtime age (BSD stat)
  LOG_MTIME="$(stat -f %m "$LOG_FILE" 2>/dev/null)"
  if [ -n "$LOG_MTIME" ]; then
    LOG_AGE=$(( NOW - LOG_MTIME ))
    if [ "$LOG_AGE" -le $(( MAX_AGE_MIN * 60 )) ]; then
      pass "$(basename "$LOG_FILE") updated $(human_age "$LOG_AGE") ago."
    else
      warn "$(basename "$LOG_FILE") last written $(human_age "$LOG_AGE") ago (stale)."
    fi
  fi
  info "last ${TAIL_LINES} lines:"
  tail -n "$TAIL_LINES" "$LOG_FILE" | sed 's/^/      /'
fi

# ---------------------------------------------------------------------------
# 5. Dashboard snapshot staleness
# ---------------------------------------------------------------------------
head2 "5. Dashboard freshness (internals_snapshot.json)"
if [ ! -f "$SNAPSHOT" ]; then
  info "snapshot not found at $SNAPSHOT (skip). Set SNAPSHOT=... to point at your checkout."
else
  if have jq; then
    PUSHED_AT="$(jq -r '.pushed_at // empty' "$SNAPSHOT" 2>/dev/null)"
    FEED_STATUS="$(jq -r '.feed_status // empty' "$SNAPSHOT" 2>/dev/null)"
  else
    PUSHED_AT="$(sed -n 's/.*"pushed_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'  "$SNAPSHOT" | head -1)"
    FEED_STATUS="$(sed -n 's/.*"feed_status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$SNAPSHOT" | head -1)"
  fi
  if [ -z "$PUSHED_AT" ]; then
    warn "could not read pushed_at from $SNAPSHOT."
  else
    P_EPOCH="$(iso_to_epoch "$PUSHED_AT")"
    if [ -z "$P_EPOCH" ]; then
      warn "pushed_at present ($PUSHED_AT) but could not parse it."
    else
      AGE=$(( NOW - P_EPOCH ))
      info "feed_status field says: ${FEED_STATUS:-<none>} · pushed_at $PUSHED_AT"
      if [ "$AGE" -le $(( MAX_AGE_MIN * 60 )) ]; then
        pass "data is $(human_age "$AGE") old (<= ${MAX_AGE_MIN}m)."
      else
        fail "data is $(human_age "$AGE") old — dashboard is STALE regardless of the FRESH field."
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
head2 "VERDICT"
case "$WORST" in
  0) printf '  %sALL CLEAR%s — VM up, port open, feed fresh.\n' "$C_GRN" "$C_RST" ;;
  1) printf '  %sDEGRADED%s — something needs a look (see WARN lines above).\n' "$C_YEL" "$C_RST" ;;
  2) printf '  %sDOWN%s — feed is broken (see FAIL lines above).\n' "$C_RED" "$C_RST"
     printf '  %sNext:%s if VM stopped -> --start; if port closed -> restart the feed agent on the guest;\n' "$C_DIM" "$C_RST"
     printf '        then re-run this doctor until VERDICT is ALL CLEAR.\n' ;;
esac
echo
exit "$WORST"
