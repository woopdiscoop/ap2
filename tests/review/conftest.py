"""Share only the generated-input builders; optional extras are loaded inside tests."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
for _sub in ("cad", "corpus", "corpus_extract", "raster"):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))
