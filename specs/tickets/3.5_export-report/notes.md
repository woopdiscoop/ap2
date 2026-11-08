# 3.5 — Router notes

Status: BLOCKED on 3.3 (needs `Layout`); final report content also uses 3.4 metrics.
DXF layers: ALE_ROOM, ALE_CIRC, ALE_LABEL, ALE_GRID, ALE_FOOTPRINT. Manual open-check in AutoCAD / ArchiCAD / Revit is done once by the user.

## Review log
- 2026-11-08 — a3d8355: 25 tests, 100 % coverage, ownership clean. Accepted: config kwarg on export_run, façade = actual contact, colours, `#k` suffix, viewBox = bbox. Rework: circulation ratio ÷ Σ net (0f8b7e7). **DONE**.
