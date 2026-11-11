"""Visual critique of a generated variant (Ticket R.6) - advisory only.

``ale critique`` renders a PNG of ``layout.json``, sends it with a compact text table to
Claude and writes ``critique.md`` / ``critique.json`` next to the variant. Nothing else in
the variant folder is ever modified.
"""

from __future__ import annotations

from ale.critique.critic import (
    CRITIQUE_JSON_NAME,
    CRITIQUE_MD_NAME,
    KINDS,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    Critique,
    CritiqueError,
    CritiqueResult,
    CritiqueUnavailableError,
    Defect,
    run_critique,
)
from ale.critique.render import LONG_SIDE, RenderedLayout, render_layout

__all__ = [
    "CRITIQUE_JSON_NAME",
    "CRITIQUE_MD_NAME",
    "KINDS",
    "LONG_SIDE",
    "PROMPT_VERSION",
    "RESPONSE_SCHEMA",
    "Critique",
    "CritiqueError",
    "CritiqueResult",
    "CritiqueUnavailableError",
    "Defect",
    "RenderedLayout",
    "render_layout",
    "run_critique",
]
