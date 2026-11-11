# Ticket R.7 · Evaluation report

Tests: `tests/raster_vlm/test_vlm_geometry.py` (client mocked, no network, no real key).

| ID | Test | Result |
|---|---|---|
| G701 | `test_G701_default_off` | pass |
| G702 | `test_G702_mapping` | pass |
| G703 | `test_G703_confirm` | pass |
| G704 | `test_G704_undersegmented` | pass |
| G705 | `test_G705_disagreement` | pass |
| G706 | `test_G706_invalid` | pass |
| G707 | `test_G707_cache` | pass |
| G708 | `test_G708_errors`, `test_G708_render_failure` | pass |
| G709 | `test_G709_gates` (lock check) + gates below | pass |

## Gates

- ruff check, ruff format --check, mypy strict on `src`: clean.
- `python -m ale.contracts.lock --check`: OK.
- Coverage (`--cov=src/ale/raster`): `vlm_reader.py` 100 %, `compare.py` 97 %.
- Whole suite: 1261 passed, 11 skipped, 3 xfailed (pre-existing, not R.7) in 703 s.

## Design notes

- Geometry is asked only from a provider exposing `read_geometry(png, prompt)` or an
  `AnthropicVlmProvider` (sibling call with the geometry schema, same client, effort "low",
  adaptive thinking, betas, `fallbacks="default"`, no sampling parameters). A labelling-only
  provider is never asked, so existing VLM runs are unchanged.
- The geometry cache entry uses the I.2 cache with prompt version `geom-v1`; only a parsed
  answer is stored.
- The extra flag `GEOMETRY_DISAGREEMENT` is inserted into `review_flags` by `extract.py`
  (`ale.join.review_flags`, outside R.7 ownership, is unchanged).
- Extract summary gains `geometry_vlm`, `geometry_classical`, `geometry_disagreements`,
  `geometry_errors`.

## Spec issues

1. RD §4 and G704: "matched IoU >= 0.6" cannot apply when the classical reader found a single
   merged room (its IoU with each of 4 VLM rooms is far below the 0.5 match threshold). The
   `< 2 classical rooms` rule is applied first and selects the VLM rooms without an IoU test;
   the 0.6 condition is applied only to the `>= 1.5x more rooms` rule.
2. G705 "mean IoU 0.4": pairs below the 0.5 match threshold are unmatched, so the mean IoU
   of matched pairs is 0; the outcome (classical kept, flag) is the same.
3. "Choice" is silent on an empty VLM answer: it never replaces the classical result and
   raises no flag.
4. Geometry reading by a provider is not part of the `VlmProvider` protocol (labelling schema
   is fixed in `AnthropicVlmProvider`); the sibling-call approach above was used.
5. `ale.join.review_flags` is outside the ownership list, so the new flag is added in the
   extract wiring rather than in `REVIEW_FLAGS`.
