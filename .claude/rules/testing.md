---
paths:
  - "tests/**"
  - "**/test_*.py"
---

- Tests are pytest, run with `uv run python -m pytest` (plain `uv run pytest` fails on
  Windows with an access-denied spawn error)
- Test settle-up with exact integer assertions, never approximate
- Never mark a test skipped or xfail to make the suite green