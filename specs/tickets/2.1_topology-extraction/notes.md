# 2.1 — Router notes

Status: BLOCKED on 1.6.
Uses `Wall.thickness` (added to the contract for this purpose) to buffer rooms by half the local wall thickness.

## Review log
- 2026-11-08 — d9cdd2c: Router spec error (buffer-area formula ≈ 0 for wall-face rooms) → facing-parallel-edge measure with 0.10 m gap tolerance accepted. Default thickness = full 0.10 m; DOOR openings only; courtyard holes not façade (kept; holes in extracted plans are often voids/stairs); config unused; problems logged. **DONE**.
