# Ticket 3.5 — Export & Report · Evaluation report

Environment: Linux, Python 3.13, `pip install -e ".[dev,excel,cad]"` (ezdxf 1.4.5).

## Results

| ID | Test(s) in `tests/export/test_export_eval.py` | Result |
|---|---|---|
| X01 | `test_X01_files`, `test_X01_refuses_any_existing_file[×4]` | pass |
| X02 | `test_X02_json` | pass |
| X03 | `test_X03_dxf_audit`, `test_X03_dxf_footprint_and_grid` | pass |
| X04 | `test_X04_dxf_geometry` | pass |
| X05 | `test_X05_dxf_labels` | pass |
| X06 | `test_X06_dxf_disabled`, `test_X06_dxf_ezdxf_missing`, `test_X06_write_dxf_without_ezdxf_raises` | pass |
| X07 | `test_X07_svg`, `test_X07_north_arrow_direction[×2]` | pass |
| X08 | `test_X08_report_sections`, `_summary`, `_surfaces`, `_violations_and_cost`, `_no_violation`, `_cost_weights_from_config` | pass |
| X09 | `test_X09_origin_offset` | pass |
| X10 | `test_X10_deterministic` | pass |
| X11 | gates below | pass |

Extra: `test_l_footprint_and_coarse_module` (L footprint, module 200 mm → grid step 6 modules,
facade contact on the reflex edges, missing placed target falls back to the spec target,
unknown `spec_id`).

Gates: whole suite 564 passed, 5 skipped; `ruff check` clean; `ruff format --check` clean;
`mypy` (strict) clean; coverage of `ale.export` 100 % line (100 % branch);
`python -m ale.contracts.lock --check` → 0.

## Spec ambiguities and readings chosen

1. **Cost weights "from config"**: the §3 signature has no config parameter. Added a
   keyword-only `config: AleConfig | None = None` (default `AleConfig()`); weights are
   `config.optimizer.weights`. `cost_breakdown` values are taken as unweighted; weighted =
   weight × value. A breakdown term with no configured weight shows `—` for weight and
   weighted value. The total row is `metrics.total_cost`.
2. **Instance suffix in labels**: "`#k` appended to the name" → `"<name> #<k>"` (space before
   `#`), `k` taken verbatim from the instance id (so zero padding is kept, e.g. `#01`).
3. **Façade oui/non**: read as the placed room's actual facade contact (a side lying on a
   footprint edge over a positive length), not the program's `needs_facade` flag.
4. **Circulation ratio**: circulation area / module-footprint area, shown in percent.
   Circulation area is recomputed from the circulation rects (not `metrics.circulation_area_m2`);
   Σ net = Σ targets of `prepared.instances`; Σ placed = Σ room rect areas.
5. **Circulation colours** ("`#ffffff` with grey hatch-free fill `#eeeeee`"): fill `#eeeeee`,
   stroke `#ffffff`.
6. **North arrow**: `north_angle_deg` taken as the clockwise angle from drawing +y to true north
   (the convention of `ale.contracts.orientation`); the arrow points along `(sin a, cos a)`.
7. **viewBox**: exactly the footprint bbox, no margin (`xmin -ymax w h`); SVG y = −drawing y.
   `width`/`height` attributes are set to 50 px per metre.
8. **Zone column**: French names (Public / Administratif / Services); `Δ %` is signed like `Δ m²`.
9. **MTEXT third line**: when a placed room has no target, only the area is shown (no Δ).
10. **Room target**: `PlacedRoom.target_area_m2`, falling back to the `RoomSpec` target if None.
11. **Grid lines**: drawn at `xmin + k·step` (and `ymin + k·step`) for every value ≤ the bbox
    max, each spanning the full bbox; the bbox edges at the start are included.
12. **FileExistsError**: checked for all four names (including `layout.dxf` when `dxf=False`),
    before anything is written.
13. **Test layouts**: `PreparedInput` built through `prepare_input` from `program_to_xlsx` /
    `site_to_yaml` (helpers of `tests/program/program_helpers.py`, imported via a `sys.path`
    entry in `tests/export/conftest.py`).
