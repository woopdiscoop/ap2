"""Fixtures of the Ticket I.2 rendering tests: reuse the raster, PDF, CAD and label helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
for _sub in ("cad", "pdfread", "raster", "labels"):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))
