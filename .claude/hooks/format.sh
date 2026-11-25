#!/bin/sh
# PostToolUse hook: format the file Claude just edited. Reads the hook JSON from stdin.
set -eu

file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')
root="$(cd "$(dirname "$0")/../.." && pwd)"

case "$file" in
  "$root"/backend/*.py)
    cd "$root/backend" && uv run --quiet ruff format "$file" >/dev/null && uv run --quiet ruff check --fix --quiet "$file" || true
    ;;
  "$root"/frontend/src/*.ts | "$root"/frontend/src/*.tsx | "$root"/frontend/src/*.css)
    cd "$root/frontend" && pnpm exec biome check --write "$file" >/dev/null 2>&1 || true
    ;;
esac
