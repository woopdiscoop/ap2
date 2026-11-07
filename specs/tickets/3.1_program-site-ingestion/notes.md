# 3.1 — Router notes

Status: BLOCKED on 0.2, 0.4 (DWG site polylines additionally need 1.2; DXF and YAML sites do not).

Parked:
- Metric footprint → module footprint: snap **inward** to the 0.6 m grid; the lost sliver area is reported. Grid origin and axes: aligned with the (rectilinear) footprint edges.
- Feasibility "expected overshoot" = Σ over rooms of the overshoot of `smallest_valid_rect` (contract function), so 3.1 and 3.3 use the same arithmetic.
