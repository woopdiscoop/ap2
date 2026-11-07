# Ticket 0.2 — Data Contracts · Evaluation

Every test ID is a named pytest test under `tests/contracts/`. The expected values below were
computed by the Router; if your implementation disagrees, report it — do not change the expectation.

## 0. Harness rules

- `pytest-timeout` 60 s/test; suite ≤ 60 s. No network. Hypothesis: `max_examples=300`, `derandomize=True`.

## 1. Units (`units.py`)

| ID | Test | Pass condition |
|---|---|---|
| U01 | exact_modules | `m_to_modules(1.8, 600) == 3`; `m_to_modules(0.6, 600) == 1`; `m_to_modules("12.0", 600) == 20`; `m_to_modules(1.75, 600)` raises `NotOnGridError`. |
| U02 | rounding_modes | `m_to_modules(1.75, 600, FLOOR) == 2`, `CEIL == 3`, `NEAREST == 3`; `mm_to_modules(900, 600, NEAREST) == 2` (half-even: 1.5 → 2); `mm_to_modules(1500, 600, NEAREST) == 2` (2.5 → 2). |
| U03 | roundtrip_property | Hypothesis, `n ∈ [-10⁶, 10⁶]`, `module_mm ∈ {100, 300, 600, 1200}`: `m_to_modules(modules_to_m(n, mm), mm) == n` and `mm_to_modules(modules_to_mm(n, mm), mm) == n`. |
| U04 | area_exact | `cells_to_m2(9, 600) == 3.24`; `m2_to_mm2(12.6) == 12_600_000`; `mm2_to_m2(8_640_000) == 8.64`. |
| U05 | module_range | `module_mm` 99, 1201, `600.0` → `ValueError`/`TypeError`. |
| U06 | no_float_modulo | AST scan of `src/ale/contracts/**/*.py`: every `BinOp` with `Mod` (and every `divmod`/`math.fmod` call) must sit on a source line ending with the comment `# int-mod` (the author's assertion that both operands are `int`); `math.fmod` is forbidden outright. The checker is unit-tested on a planted violation. |

## 2. Area rule (`area_rule.py`) — default tolerance (−3 % / +max(3 %, 1.2 m²)); `grid` = `grid600 = GridSpec(module_mm=600)` unless stated (the 0.60 m cases come from the directive's worked examples; the default grid is now 0.10 m, see A10)

| ID | Test | Pass condition |
|---|---|---|
| A01 | directive_table | `best_buildable_rect(T, grid, 1.0, 2.0, tol)` returns `(short, long)` = 3 m² → `(3, 3)` (3.24 m²) · 4 → `(3, 4)` (4.32) · 6 → `(3, 6)` (6.48) · 8 → `(4, 6)` (8.64) · 12 → `(5, 7)` (12.60) · 7.5 → `(4, 6)` (8.64, Δ = +1.14). |
| A02 | cap_gap | `best_buildable_rect(7.43, grid, 1.0, 2.0, tol) is None` (2.4×3.0 = 7.20 < −3 %; 2.4×3.6 = 8.64 > +1.2 m²). This documents the gap 7.423–7.439 m² in the 1:1–1:2 band. |
| A03 | bounds_exact | `module_mm = 100` (1 cell = 0.01 m²), T = 10 m²: `area_bounds_mm2 == (9_700_000, 11_200_000)`; `check_area` valid for rect 97×10 (9.70 m²) and 10×112 (11.20 m²); invalid for 19×51 (9.69 m²) and 19×59 (11.21 m²). *(Corrected 2026-11-07: the first version used 97×100 etc., which are 100× too large — Router error caught by the Worker.)* |
| A04 | pct_regime | T = 60 m²: upper bound is `60 + 1.8 = 61.8 m²` (3 % > 1.2 m²) → `area_bounds_mm2(60)[1] == 61_800_000`. |
| A05 | check_fields | `check_area(ModuleRect(0,0,4,6), grid600, 7.5, tol)`: `valid`, `placed_m2 == 8.64`, `delta_m2 == 1.14` (±1e-9), `overshoot_m2 == 1.14`, `delta_pct ≈ 15.2`. |
| A06 | narrow_band | `best_buildable_rect(11.9, grid, 1.5, 2.0, tol) is None` (a 1:1.5–1:2 band cannot meet the cap there); `best_buildable_rect(11.9, grid, 1.0, 2.0, tol) == (5, 7)`. |
| A07 | min_side | `best_buildable_rect(3, grid, 1.0, 2.0, tol, min_short_side_modules=4) is None` (the smallest candidate 4×4 = 5.76 m² exceeds 3 + 1.2 m²). |
| A08 | bounded | `best_buildable_rect(10_000, grid, 1.0, 1.0, tol, max_side_modules=200) == (167, 167)` (10 040.04 m², the smallest square ≥ target), returned in < 1 s. With `max_side_modules=160` → `None`. |
| A09 | rounds_up | `best_buildable_rect(3.3, grid600, 1.0, 2.0, tol) == (3, 4)` (4.32 m²) — **not** `(3, 3)` (3.24 m², valid but below target). |
| A10 | fine_grid | `module_mm = 100`, band 1.0–2.0: `best_buildable_rect(7.43, …) == (24, 31)` (7.44 m²); `best_buildable_rect(10_000, …, 1.0, 1.0, …) == (1000, 1000)`. Scan T = 2.00 … 60.00 m² in 0.01 steps (5 801 targets): every T has a result, none below target, max overshoot ≤ 0.11 m² (Router-computed). Whole scan < 10 s. |

## 3. Orientation (`orientation.py`)

| ID | Test | Pass condition (degrees) |
|---|---|---|
| O01 | bearings_north_up | `north_angle_deg = 0`: (0,1) → 0, (1,0) → 90, (0,−1) → 180, (−1,0) → 270. |
| O02 | bearings_rotated | `north = 90`: (1,0) → 0, (0,1) → 270. `north = 30`: (0,1) → 330. |
| O03 | bins | `bearing_bin`: 0 → N, 44.999 → N, 45 → E, 134.9 → E, 135 → S, 225 → W, 314.9 → W, 315 → N, 359.99 → N. |
| O04 | normals | CCW `ModulePolygon [(0,0),(4,0),(4,3),(0,3)]` → normals `(0,−1), (1,0), (0,1), (−1,0)`. |

## 4. Taxonomy

| ID | Test | Pass condition |
|---|---|---|
| T01 | load_valid | Packaged `taxonomy.yaml` loads; 75 types (2 of category SPECIAL: `outdoor_space`, `unknown`); `version == "1.1.0"`; byte-identical to `specs/tickets/0.2_contracts/taxonomy.v1.yaml`. |
| T02 | integrity_errors | Synthetic taxonomies with (a) duplicate key, (b) a canonical synonym shared by two types (`"S.REUNION"` in two types), (c) missing `unknown`, (d) bad key `Office` → each raises `ValueError` naming the problem. |
| T03 | normalisation_table | `normalize_label(raw) → (key, rule)` exactly as below. |
| T04 | canonical_forms | `canonical_input` equals the middle column below. |
| T05 | room_type_validator | `RoomSpec(type="office", …)` ok; `type="kitchen"` → `ValidationError`; `type="unknown"`, `type="outdoor_space"` and `type="circulation"` → `ValidationError` (not allowed in a program). |

| raw | canonical_input | key | rule |
|---|---|---|---|
| `S. REUNION` | `S REUNION` | meeting_room | exact |
| `Salle de Réunion 2` | `SALLE DE REUNION` | meeting_room | exact |
| `Bur.12` | `BUR` | office | exact |
| `BUREAU 12,40 m²` | `BUREAU` | office | exact |
| `101 BUREAU` | `BUREAU` | office | exact |
| `WC H/F` | `WC HF` | sanitary | exact |
| `wc h/f 3` | `WC HF` | sanitary | exact |
| `S.D.R.` | `SDR` | meeting_room | exact |
| `LOCAL TECH.` | `LOCAL TECH` | technical_room | exact |
| `Local technique R+1` | `LOCAL TECHNIQUE R` | technical_room | prefix |
| `DGT` | `DGT` | circulation | exact |
| `OFFICE` | `OFFICE` | kitchenette | exact |
| `SALLE` | `SALLE` | unknown | none |
| `Bureau paysager nord` | `BUREAU PAYSAGER NORD` | open_office | prefix |
| `B12 ARCHIVES` | `ARCHIVES` | archive | exact |
| `W.C.` | `WC` | sanitary | exact |
| `12,40 m²` | `` | unknown | none |
| `` | `` | unknown | none |
| `Esc. A` | `ESC A` | stair | prefix |
| `Hall d’entrée` | `HALL D ENTREE` | entrance_hall | exact |
| `LOC. MÉNAGE` | `LOC MENAGE` | cleaning_room | exact |
| `Accueil / attente` | `ACCUEIL ATTENTE` | reception | prefix |
| `VESTIAIRES H/F` | `VESTIAIRES HF` | locker_room | exact |
| `XYZ` | `XYZ` | unknown | none |
| `Chambre froide positive` | `CHAMBRE FROIDE POSITIVE` | cold_room | exact |
| `Chambre 12` | `CHAMBRE` | bedroom | exact |
| `Loge gardien` | `LOGE GARDIEN` | security_room | exact |
| `Salle informatique` | `SALLE INFORMATIQUE` | computer_room | exact |
| `Local informatique` | `LOCAL INFORMATIQUE` | it_room | exact |
| `C.D.I.` | `CDI` | library | exact |
| `Amphi A` | `AMPHI A` | lecture_hall | prefix |
| `Plateau scénique` | `PLATEAU SCENIQUE` | stage | exact |
| `Espace d'attente sécurisé` | `ESPACE D ATTENTE SECURISE` | safe_refuge | exact |
| `Terrasse` | `TERRASSE` | outdoor_space | exact |
| `Salle de classe 103` | `SALLE DE CLASSE` | classroom | exact |

## 5. Models

| ID | Test | Pass condition |
|---|---|---|
| M01 | roundtrip_json | For a hand-built, fully populated instance of each of `RoomSpec, Program, SiteSpec, Layout, PlanGeometry, Rulebook, PolishExpression`: `Model.model_validate_json(canonical_json(x)) == x`. |
| M02 | roundtrip_yaml | Same for `Rulebook`, `Program`, `SiteSpec` via `dump_yaml`/`load_yaml`; and `dump_yaml(load_yaml(dump_yaml(x))) == dump_yaml(x)`. |
| M03 | strict_ints | `ModuleRect(x=1.0, …)`, `ModuleRect(x="1", …)`, `ModuleRect(x=True, …)` → `ValidationError`; `RoomSpec(target_area_m2=12)` ok (int accepted for float); `RoomSpec(target_area_m2="12")` → error. |
| M04 | frozen_extra | Assigning a field raises; unknown field `colour=` raises — for every model. |
| M05 | program_rules | Duplicate ids; unknown reference in `adjacent_to`; self-reference; A requires B while B avoids A; `floor=1` → each `ValidationError`. `Program.instances()` for quantity 12 yields `R1#01 … R1#12`; quantity 1 yields `R1`. |
| M06 | module_polygon | Non-rectilinear, clockwise, self-intersecting, collinear-vertex, and 3-vertex inputs each rejected; L-shape `[(0,0),(10,0),(10,4),(6,4),(6,8),(0,8)]` accepted with `area_cells() == 64`. |
| M07 | rect_overlap | `ModuleRect(0,0,4,4).intersection_cells(ModuleRect(2,2,4,4)) == 4`; touching edges → 0; disjoint → 0. |
| M08 | placed_room | `PlacedRoom(rect=ModuleRect(0,0,4,6), target_area_m2=7.5).area_m2(GridSpec(module_mm=600)) == 8.64`; `GridSpec().module_mm == 100`, `aspect_ratio() == 1.5`, `bbox_m == (0.0, 0.0, 2.4, 3.6)`, `area_delta_m2 ≈ 1.14`; circulation room → `area_delta_m2 is None`. |
| M09 | polish_expression | Valid: `a b V`, `a b V c H`, `a b c V H`, `a b H c H`. Invalid: `a b`, `a V`, `a b V V`, `a b c H H` (not normalised), `a a V` (duplicate leaf). `leaves("a b V c H") == ("a","b","c")`. |
| M10 | plan_geometry | Scale/method coupling enforced; bad `host_wall` index rejected; `to_metric()` on a Y_DOWN plan with scale 0.01: point (100, 50) → (1.0, −0.5); opening `width_native=90` → `width_m == 0.9`; `to_metric()` with unknown scale raises. |
| M11 | rulebook_rules | `Quantiles(p10=2, p50=1.5, p90=3)` rejected; aspect p10 < 1 rejected; orientation with 3 bearings rejected; `AdjEntry(a="sanitary", b="office")` is stored as `a="office", b="sanitary"`; pairs given unsorted come back sorted; `(office, sanitary)` + `(sanitary, office)` → duplicate rejected; `kind="seed"` without `author` or with `date="07/11/2026"` rejected; `Adjacency.p("office","meeting_room") == p("meeting_room","office")`; unlisted pair → `default_p`; `types` keys `circulation` and `outdoor_space` rejected. |
| M12 | rulebook_hash | `content_sha256()` is stable across processes (compute in a subprocess) and changes when any `p` changes. |

## 6. Serialisation, schemas, helpers

| ID | Test | Pass condition |
|---|---|---|
| J01 | canonical_bytes | Two `Rulebook`s built with dict insertion orders reversed → identical `canonical_json` bytes. Output ends with `\n`, contains no spaces after separators, and `NaN` raises. |
| J02 | schema_no_drift | `python -m ale.contracts.export_schemas --check` exits 0 on the committed tree; exits 1 after a byte is changed in one schema file (tmp copy). |
| J03 | schemas_validate | A canonical-JSON dump of each M01 instance validates against its exported JSON Schema with `jsonschema` (Draft 2020-12). |
| J04 | validate_cli | `python -m ale.contracts.validate rulebook <file>` → `OK` exit 0 for a valid file; for a file with `types.office.aspect.p10: null` → exit 1 and a line starting `types.office.aspect.p10:`. |
| J05 | lock | `python -m ale.contracts.lock` then `--check` → exit 0; modify any contract file → `--check` exits 1 naming the file. |
| J06 | import_light | `import ale.contracts.models` in a fresh interpreter takes < 2 s and does not import `numpy`, `networkx`, `pandas`, `torch`. |

## 7. Static gates

| Gate | Threshold |
|---|---|
| `ruff check` / `ruff format --check` on owned files | clean |
| `mypy --strict src/ale/contracts` | 0 errors |
| Coverage `--cov=ale.contracts --cov-branch` | ≥ 90 % line, ≥ 80 % branch |
| Ownership (`git diff --name-only`) | only RD §3 paths |

## 8. Merge procedure

Same as Ticket 0.1. After both 0.1 and 0.2 are `DONE`, the Router runs `python -m ale.contracts.lock`,
commits `CONTRACTS.lock`, and the contracts are frozen at `1.0.0`.
