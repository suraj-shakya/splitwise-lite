#!/usr/bin/env bash
# PreToolUse(Bash) hook: dependencies are a deliberate decision (see CLAUDE.md).
#
# Greps the raw hook payload instead of parsing JSON, so it needs no jq (not
# installed on Windows) and fails closed: if the payload is ever malformed the
# grep still matches and the install is still blocked.
input=$(cat)

if printf '%s' "$input" | grep -qE '(uv add|pip install|poetry add)'; then
  echo "Blocked: dependencies are a deliberate decision. Declare it in pyproject.toml, then run 'uv sync'." >&2
  exit 2
fi
exit 0
