# Ticket 2.1 — Topology extraction from extracted plans · Requirements
> **Worker brief.** Context = this file, `eval.md`, the contracts (`src/ale/contracts/`: `PlanGeometry`, `Wall`, `Opening`, `LabelledPolygon`, `TextItem`, `Polygon`, `LineString`, enums, `taxonomy`), `ale.guards`, `ale.config`, test helpers. **Library only** — no CLI wiring (a later integration ticket wires `ale extract`/`ale review`). Do not modify contracts or other packages. All loops bounded; public functions never raise on bad input (problems → warnings).
## Files
`src/ale/mining/{__init__,topology}.py`, `tests/mining/**`, `specs/tickets/2.1_topology-extraction/eval_report.md`.
## API
```python
class Contact(BaseModel, frozen=True): a: str; b: str; kind: ContactKind; shared_m: float; openings: int   # a < b (room ids)
class PlanTopology(BaseModel, frozen=True):
    source_sha256: str; page: int; plan_index: int; fidelity: Fidelity
    rooms: tuple[tuple[str, str | None, float], ...]   # (room id, type or None, area m²)
    contacts: tuple[Contact, ...]                      # sorted by (a, b)
    exterior: tuple[tuple[str, float], ...]             # (room id, façade length m), rooms touching the plan's outer boundary
def extract_topology(plan: PlanGeometry, config: AleConfig) -> PlanTopology | None    # None if scale unknown
```
## Rules
- Work in metres (`plan.to_metric()`). Buffer each room polygon by half the local wall thickness (median thickness of walls within 1 m; default 0.10 m if none) before the touch test.
- Shared length = length of the intersection of the two buffered boundaries' overlap region's centreline (implement as: length of `buffer_a ∩ buffer_b` area / (2 × half-thickness)); contact kept if ≥ 0.6 m → `WALL`.
- `DOOR` if ≥ 1 opening's segment midpoint lies within the shared region (count them).
- Exterior: room boundary length within 0.3 m of the union-of-rooms outer boundary → façade length.
- Fidelity from `fidelity_of(plan.source_kind)`. Deterministic ordering.
