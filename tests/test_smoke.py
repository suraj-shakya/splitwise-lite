"""Smoke test: proves the package imports and the test harness runs.

Task 1 of plans/backlog.md exists to make every later task verifiable.
"""

from splitwise_lite import __version__


def test_package_exposes_its_version() -> None:
    assert __version__ == "0.1.0"
