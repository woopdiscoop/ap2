"""Rulebook build (Ticket 2.2): mined statistics blended with an optional seed.

Public API: :func:`build_rulebook` (pure) and :func:`run_build` (workspace → files).
"""

from __future__ import annotations

from ale.rulebook.build import (
    BuildResult,
    RunResult,
    SeedError,
    build_rulebook,
    load_seed,
    run_build,
)

__all__ = ["BuildResult", "RunResult", "SeedError", "build_rulebook", "load_seed", "run_build"]
