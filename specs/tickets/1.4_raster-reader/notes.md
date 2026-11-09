# 1.4 — Router notes

Status: BLOCKED on 1.1 and the test corpus. O-4 resolved (U-4, academic non-commercial use): CubiCasa5K may be used.

Parked:
- CubiCasa5K data/weights: CC BY-NC-SA 4.0 — compatible with the project's academic, non-commercial use. Obligations: attribution (cite the CubiCasa5K paper and repository), and **share-alike**: any fine-tuned weights or derived dataset we publish must carry CC BY-NC-SA 4.0. Weights stay out of the repository (manual download, SHA-256 pinned).
- Domain gap: CubiCasa5K is residential; commercial plans are out of distribution regardless of licence.
- Earlier v2.0 work on a CubiCasa-based vectoriser spec is in git history (commit before the v2.2 restructure) and can be reused if option (a) is chosen.

## Review log
- 2026-11-09 — 1f66d95: R1–R8 pass, 99 % coverage. Accepted: explicit gap bridging before closing (spec's closing-by-thickness cannot seal 4–9× gaps), run-length thickness, richer plan score (documented in read.py), mapping back to input pixels. Real-corpus smoke: robust but under-segments rendered web plans; door over-count. **DONE**.
