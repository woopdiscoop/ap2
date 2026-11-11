"""``ale score`` (Ticket R.10): score an existing scheme (PDF/DXF) against a programme."""

from __future__ import annotations

from ale.score.match import (
    DrawnRoom,
    Line,
    Match,
    PlanInfo,
    Sheet,
    assign,
    extract_sheet,
    lines_from_program,
    match_lines,
)
from ale.score.report import ScoreResult, build_score, render_markdown, write_outputs

__all__ = [
    "DrawnRoom",
    "Line",
    "Match",
    "PlanInfo",
    "ScoreResult",
    "Sheet",
    "assign",
    "build_score",
    "extract_sheet",
    "lines_from_program",
    "match_lines",
    "render_markdown",
    "write_outputs",
]
