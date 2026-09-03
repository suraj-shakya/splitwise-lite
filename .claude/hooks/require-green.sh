#!/usr/bin/env bash
# Stop hook: refuse to finish the turn while the suite is red.
cd "$CLAUDE_PROJECT_DIR" || exit 0

input=""
[ -t 0 ] || input=$(cat)

# Claude Code sets stop_hook_active when it is already re-running because this
# hook blocked. Bail out then, or a suite that cannot go green loops forever.
if printf '%s' "$input" | grep -qE '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

out=$(mktemp) || exit 0
trap 'rm -f "$out"' EXIT

if ! uv run python -m pytest -q > "$out" 2>&1; then
  echo "Test suite is red. Not finished." >&2
  tail -20 "$out" >&2
  exit 2
fi
exit 0
