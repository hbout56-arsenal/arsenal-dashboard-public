#!/usr/bin/env bash
# INBOX RESET dispatch — run every self-test + the three dispatch tests (T1/T2/T3).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== py_compile =="
python3 -m py_compile inbox_reset/*.py && echo "  py_compile OK"
echo "== internals_context self-test =="; python3 inbox_reset/internals_context.py --selftest
echo "== ten_am_read self-test (incl T1) =="; python3 inbox_reset/ten_am_read.py --selftest
echo "== shadow_email self-test (incl T3) =="; python3 inbox_reset/shadow_email.py --selftest
echo "== T2 verify_suspensions =="; python3 inbox_reset/verify_suspensions.py
echo "ALL GREEN"
