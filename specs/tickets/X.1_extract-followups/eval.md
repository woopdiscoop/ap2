# Ticket X.1 · Evaluation (no network; VLM mocked where used)

| ID | Test | Pass condition |
|---|---|---|
| X01 | force_all | After a normal run, `--force` re-extracts every unit (EXTRACTED and EXCLUDED); outputs byte-identical; one `extract_forced` event per unit; `review_flags` not duplicated. |
| X02 | force_kind | `--force --kind pdf` touches only PDF units. |
| X03 | exclusive | `--force --only-new` → exit 2, French message, nothing changed. |
| X04 | force_cache | With a mocked provider: first run N calls; `--force` re-run 0 calls (all cache hits), identical output. |
| X05 | extent | `plan_image` on a W × H raster returns `(-0.5, -0.5, W-0.5, H-0.5)`; a mock box on a 1-pixel-wide wall maps exactly onto that pixel's edges (`normalized_to_native`). |
| X06 | gates | ruff, format, mypy strict; coverage of touched modules not lower than before (path-form `--cov`); lock --check; whole suite passes. |
