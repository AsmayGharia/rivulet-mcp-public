#!/usr/bin/env bash
# Record all rivulet GIFs. Run from project root with your API key set:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   bash gifs/record.sh
set -euo pipefail

VENV="$(cd "$(dirname "$0")/.." && pwd)/.venv"
RIVULET="$VENV/bin/rivulet"
GIFS_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "Error: ANTHROPIC_API_KEY not set" >&2
  exit 1
fi

record_gif() {
  local name="$1"
  local cmd="$2"
  local cast="$GIFS_DIR/${name}.cast"
  local gif="$GIFS_DIR/${name}.gif"

  echo "Recording $name..."
  asciinema rec --overwrite --command "bash -c '$cmd'" "$cast"
  echo "Converting $name to GIF..."
  agg --theme monokai "$cast" "$gif"
  echo "Done → $gif"
}

# 1. presets — no API call, instant
record_gif "presets" "$RIVULET presets"

# 2. design — shows thinking stream
record_gif "design" "$RIVULET design 'screen 5 kinase inhibitors against T-cells'"

# 3. iterate — pipe design into iterate
record_gif "iterate" \
  "$RIVULET design 'screen 5 kinase inhibitors against T-cells' --json \
   | $RIVULET iterate - 'add NK cells as a second cell type'"

echo ""
echo "All GIFs written to $GIFS_DIR"
