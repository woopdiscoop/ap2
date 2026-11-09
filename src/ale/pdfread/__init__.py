"""Vector-PDF reader (Ticket 1.3): one PDF page → ``PlanGeometry`` in PDF points.

Needs the ``pdf`` extra (PyMuPDF) at call time; importing :mod:`ale.pdfread` imports
PyMuPDF only lazily, inside :func:`read_pdf_page`.
"""

from __future__ import annotations

from ale.pdfread.read import PdfReadResult, plan_likeness, read_pdf_page
from ale.pdfread.scale import ScaleResult, ScaleText, find_scale, m_per_pt, scale_tokens

__all__ = [
    "PdfReadResult",
    "ScaleResult",
    "ScaleText",
    "find_scale",
    "m_per_pt",
    "plan_likeness",
    "read_pdf_page",
    "scale_tokens",
]
