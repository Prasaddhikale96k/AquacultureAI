"""pytest configuration and environment defaults.

AMENDMENT A1:
AQUA_AUTH_MODE defaults to full in the shipping app, but the existing pytest suite
must run in open mode so all existing tests run unchanged.
Only the new test_auth_*.py tests explicitly set AQUA_AUTH_MODE=full via their own fixture/env override.
"""
import os
from pathlib import Path

os.environ.setdefault("AQUA_AUTH_MODE", "open")


def pytest_runtest_setup(item):
    """Hook running before every test: ensures open mode for pre-existing tests and jobs dir exists."""
    if "test_auth_" not in item.nodeid:
        os.environ["AQUA_AUTH_MODE"] = "open"
    data_dir = os.environ.get("AQUA_BACKEND_DATA")
    if data_dir:
        (Path(data_dir) / "jobs").mkdir(parents=True, exist_ok=True)

