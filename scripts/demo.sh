#!/usr/bin/env bash
# Governance-as-code MVP demo (Git Bash on Windows, or any bash).
#   1. compile the Spectral rulesets from the catalogs
#   2. instantiate and assess V1-V4 on recorded LLM/Decider outputs (and recorded CALM/Spectral unless REAL_TOOLS=1)
#   3. start the dashboard on http://127.0.0.1:8001 and open it in the browser
# Usage: bash scripts/demo.sh            (Ctrl+C stops the dashboard)
#        REAL_TOOLS=1 bash scripts/demo.sh   (runs the installed calm and spectral CLIs)
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8001
URL="http://127.0.0.1:${PORT}/"

echo "== uv sync"
uv sync --quiet

echo "== compile rulesets (APPROVED catalog items only)"
uv run python -m rule_authoring.consistency
uv run python -m rule_authoring.compile

echo "== instantiate and assess V1-V4"
if [[ "${REAL_TOOLS:-0}" == "1" ]]; then
  uv run python -m governance_execution.demo --real-tools
else
  uv run python -m governance_execution.demo
fi

echo "== dashboard on ${URL}"
( sleep 3
  if command -v start >/dev/null 2>&1; then start "" "$URL"
  elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  elif command -v open >/dev/null 2>&1; then open "$URL"
  else echo "open ${URL} in your browser"; fi ) &
exec uv run python -m governance_execution.dashboard.app
