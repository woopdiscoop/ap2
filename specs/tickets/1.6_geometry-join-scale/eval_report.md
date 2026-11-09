# Ticket 1.6 — Scale reconciliation & review flags · Evaluation report

Platform of this run: Linux, Python 3.13. Whole suite: **841 passed, 7 skipped, 2 xfailed**
(xfails belong to other tickets). Ticket tests (`tests/join`): **64 passed**.

## Results

| ID | Test(s) (`tests/join/test_join_eval.py`) | Result |
|---|---|---|
| J1 | `test_J1_hierarchy` (6 crafted plans: DRAWING_UNITS > META_CSV > TITLE_BLOCK > DIMENSION_TEXT > DOOR_MEDIAN > UNKNOWN), `test_J1_cad_drawing_units_untouched_geometry` | PASS |
| J2 | `test_J2_meta_pdf` (exactly `50*0.0254/72`), `test_J2_meta_raster` (exactly `100*0.0254/300`), `test_J2_meta_csv_strings` | PASS |
| J3 | `test_J3_dimensions` (0.01 m/px within 0.5 %, outlier `12` ignored), `test_J3_outlier_ignored_but_not_enough_without_third_text` | PASS |
| J4 | `test_J4_doors` (300 rejected, `0.9/90`, confidence 0.5), `test_J4_two_doors_not_used` | PASS |
| J5 | `test_J5_widths[...]` (4 plans: `width_m == width_native * scale` exactly, contract re-validation, `to_metric`) | PASS |
| J6 | `test_J6_flags[...]` (10 crafted plans, exact flag tuples), `test_J6_review_confidence_from_config`, `test_J6_flags_after_resolution` | PASS |
| J7 | ruff check, ruff format --check, mypy strict (86 files): clean. `python -m ale.contracts.lock --check`: OK (exit 0). Coverage of `ale.join` (branch): **100 %** (`review.py` 100 %, `scale.py` 100 %). Whole suite green. | PASS |

Edge cases (`tests/join/test_join_units.py`): meta parsing (CAD units, bad/empty values,
comma decimals, raster without dpi, scanned PDF), dimension heuristics (cm integers, mm
four-digit CAD values, decimal metres, unusable texts, plausibility filter, largest cluster),
existing scales kept, idempotence, width refresh on re-scale, never-raise paths.

## Interpretations and spec issues

1. **API defaults.** `resolve_scale(plan, *, meta=None, config=None)` and
   `review_flags(plan, config=None)`: the RD's arguments are accepted as written; `None`
   config means `AleConfig()` defaults. `meta` is any mapping (CSV row: numbers or strings).
2. **Paper units (level 2).** "`scale_1_to` + paper units" is read as: native unit is the PDF
   point (1/72 in) for `PDF_VECTOR`, the pixel for `RASTER`/`PDF_SCANNED` (needs `dpi`).
   `units_label` `"pt"`/`"px"` overrides the default by source kind. CAD uses `units`
   (m, dm, cm, mm, km, in, ft and spellings). No `paper_units` key is read.
3. **Scanned PDFs.** With no `dpi` in meta, `PDF_SCANNED` falls back to
   `config.extract.raster_dpi` (ALE renders those pages itself); `RASTER` without `dpi`
   falls through with a warning, as the RD says.
4. **Existing scales.** `SCALE_BAR` (in the enum but not in the RD hierarchy) is treated
   like `TITLE_BLOCK` (level 3). An existing `META_CSV`/`DIMENSION_TEXT`/`DOOR_MEDIAN` scale
   counts at its own level, so re-running is idempotent.
5. **Dimension texts.** The m/cm/mm readings of one value give 3 equally large clusters, so
   the RD rule alone cannot choose. Added: (a) a plausibility filter (paper scales 1:10 to
   1:5000; 50 to 1200 dpi for pixels; 1e-4 to 10 m/unit for CAD); (b) a tie-break by number
   format (a decimal number reads as m, a 4+ digit integer as mm, other integers as cm).
   "Parallel" means within 10° of the text rotation (native frame). The distance is
   measured from the insert point. Texts with no height are skipped (no 3 × height
   threshold). Comma decimals (`3,60`) are accepted.
6. **Doors.** "≥ 3 doors" is applied both before and after outlier rejection. The scale
   uses the median of the doors that remain (this gives J4's `0.9/90`).
7. **Flags.** `scale_low_confidence` is raised only when a scale is known (an unknown
   scale gives `scale_unknown` only). Area flags need a scale. `area_mismatch` uses
   `|metric − text| > 5 % × text`. `many_untyped` uses strictly more than 30 %. The order
   is fixed (`REVIEW_FLAGS`).
8. **Widths.** `width_m = width_native * scale` (plain float product, within the
   contract's 1e-6 tolerance of its exact-decimal `_mul`). With an unknown scale, openings
   are left untouched.
