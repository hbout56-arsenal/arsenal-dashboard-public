#!/usr/bin/env bash
# DISPATCH 44 — Risk & Survival layer runner. Order matters: the pre-trade
# checklist reads the outputs of the limit/heat/regime views.
# ADVISORY / SIMULATED. Generates computed views only; does NOT touch index.html.
set -euo pipefail
cd "$(dirname "$0")"
echo "== Phase 1A risk_model =="     ; python3 risk_model.py
echo "== Phase 1B loss_limits =="    ; python3 loss_limits.py
echo "== Phase 2A portfolio_heat ==" ; python3 portfolio_heat.py
echo "== Phase 2B edge_by_regime ==" ; python3 edge_by_regime.py
echo "== Phase 3A pretrade_checklist ==" ; python3 pretrade_checklist.py
echo "== Phase 3B slippage =="       ; python3 slippage.py
echo "== Phase 3C mae_mfe =="        ; python3 mae_mfe.py
echo "== done — computed views written to repo root (NOT loaded into dashboard) =="
