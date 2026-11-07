# 3.3 — Router notes

Status: BLOCKED on 0.2, 0.3, 0.4 (consumes a `PolishExpression`; does not need 3.2's code, only a tree — could be dispatched in parallel with 3.2).

Parked — needs decision O-2 before specification:
- When no rectangle within a type's aspect band meets the area rule (e.g. 7.43 m² in a 1:1–1:2 band; ~11 % of targets in a 1.5–2.0 band), which constraint gives way: aspect band (soft) or area rule (report violation)?
- Directive §3.B.5 says the largest overshoot needed in the 1:2 band is +1.14 m²; exact computation gives +1.217 m² at T ≈ 7.423 m² (gap 7.423–7.439 m²). The 1:2.5 band's maximum is +1.04 m², not ≤ 0.9 m² (cap still never reached).
