#!/usr/bin/env bash
# PostToolUse(Write|Edit) hook: report the suite after a Python edit. Never blocks.
cd "$CLAUDE_PROJECT_DIR" || exit 0

input=""
[ -t 0 ] || input=$(cat)

# Only spend a second on pytest when the edited file was Python. Anchored on the
# path key so it cannot match a stray ".py" elsewhere in the payload.
if [ -n "$input" ] && \
   ! printf '%s' "$input" | grep -qE '"(file_path|filePath)"[[:space:]]*:[[:space:]]*"[^"]*\.py"'; then
  exit 0
fi

uv run python -m pytest -q 2>&1 | tail -20
exit 0
