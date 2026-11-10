# Ticket R.7 · Evaluation (client mocked)
| ID | Test | Pass condition |
|---|---|---|
| G701 | default_off | No provider → extraction byte-identical to before on the raster fixtures; no call. |
| G702 | mapping | Mock returns the exact normalised polygons of a synthetic 3-room raster → native polygons equal the drawn rooms within 0.5 px (pixel-edge extent). |
| G703 | confirm | Classical finds the 3 rooms and VLM agrees (IoU ≥ 0.8) → classical kept, no flag. |
| G704 | undersegmented | Classical finds 1 merged room, VLM finds 4 (matched IoU ≥ 0.6) → VLM rooms used; warning `géométrie : VLM`. |
| G705 | disagreement | Classical 3 rooms, VLM 3 rooms shifted (mean IoU 0.4) → classical kept, flag `GEOMETRY_DISAGREEMENT` stored in `review_flags`. |
| G706 | invalid | Self-intersecting, out-of-image and degenerate polygons → repaired / clipped / dropped with warnings; never raises. |
| G707 | cache | Second forced run (`--force`): 0 calls, identical output. |
| G708 | errors | Provider error / refusal → classical result kept, warning, exit 0. |
| G709 | gates | ruff, format, mypy strict; coverage of the new modules ≥ 90 % (path-form); lock --check; whole suite passes. |
