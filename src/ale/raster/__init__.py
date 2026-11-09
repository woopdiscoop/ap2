"""Raster reader (Ticket 1.4): classical computer vision, v1 (no learned model).

Needs the ``raster`` extra (``opencv-python-headless``, ``Pillow``) at call time and the
``pdf`` extra (``pymupdf``) for :func:`rasterize_pdf_page`; importing :mod:`ale.raster`
imports neither (the pipeline modules are imported lazily by :func:`read_raster`).
"""

from __future__ import annotations

from ale.raster.read import RasterReadResult, plan_score, rasterize_pdf_page, read_raster

__all__ = ["RasterReadResult", "plan_score", "rasterize_pdf_page", "read_raster"]
