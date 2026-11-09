# 1.3 — Router notes

Status: BLOCKED on 1.1 and the test corpus. O-8 resolved (U-4): PyMuPDF may be used.

Parked:
- PyMuPDF is AGPL-3.0: fine for an academic project; if the code is published, publish it under an AGPL-compatible licence (see board O-10).
- Two scales on one page: rule "nearest to the plan" needs a plan-extent definition first.

## Review log
- 2026-11-08 — 13dbfcb: P1–P8 pass; HABS PDFs correctly not vector plans. Rework: plan-likeness must not depend on wall-piece counts (P2 had to be drawn with 8 rectangles) → rule amended (merged walls ≥ 4, rooms ≥ 2, wall length ≥ 0.6 × diagonal). Other readings accepted.
