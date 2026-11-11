"""Fixtures of the Ticket R.7 tests (VLM geometry reader; the client is always mocked)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
for _sub in ("corpus_extract", "raster"):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALE_VLM_API_KEY", raising=False)
