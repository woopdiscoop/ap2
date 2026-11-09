"""Ticket 1.3 P7 real-corpus smoke (optional, never in CI) and P8 gates (lock part)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pdf_helpers import read

from ale.contracts.lock import main as lock_main


def test_P7_real_corpus_smoke() -> None:
    corpus = os.environ.get("ALE_CORPUS_DIR", "")
    if not corpus:
        pytest.skip("ALE_CORPUS_DIR not set (optional smoke test, never in CI)")
    pdfs = sorted(
        p for p in Path(corpus).rglob("*") if p.suffix.lower() == ".pdf" and "HABS" in p.name
    )
    print(f"\nP7: {len(pdfs)} HABS PDF(s) under {corpus}")
    for p in pdfs:
        res = read(p, 0)
        rooms = sum(len(plan.rooms) for plan in res.plans)
        walls = sum(len(plan.walls) for plan in res.plans)
        print(
            f"  {p.name}: likely={res.is_plan_likely} plan_score={res.plan_score:.3f} "
            f"walls={walls} rooms={rooms} warnings={list(res.warnings)[:3]}"
        )


def test_P8_gates() -> None:
    """Contracts untouched (lock --check); ruff/mypy/coverage run as commands (eval_report)."""
    assert lock_main(["--check"]) == 0
