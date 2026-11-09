# Try ALE in 5 minutes

Ready-made inputs to run the layout generator without preparing anything.

| Files | Program | Site |
|---|---|---|
| `p08_programme.xlsx` + `p08_site.yaml` | small office, 8 rooms | rectangle |
| `p25_programme.xlsx` + `p25_site.yaml` | medium office, 25 rooms (334 m²) | 24 × 18 m rectangle |
| `p60_programme.xlsx` + `p60_site.yaml` | large office, 60 rooms | L-shaped footprint |
| `rulebook_seed_draft.yaml` | draft rulebook (awaiting architect validation) | |
| `rulebook_test.yaml` | rulebook used by the test suite | |

## 0. See results without installing

`sample_output/p25/` holds a real run on the 25-room example (seed 42, 2 variants, draft rulebook):
[summary](sample_output/p25/summary.md) ·
[variant 2 preview](sample_output/p25/variant_02/preview.svg) ·
[variant 2 report](sample_output/p25/variant_02/report.md) ·
`variant_02/layout.dxf` (download, open in a DXF viewer).

## 1. Install (once)

Python 3.11, 3.12 or 3.13. From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[excel,cad]"
```

## 2. Create a workspace

```bash
ale init --workspace my_ws
```

## 3. Generate layouts

```bash
ale generate --workspace my_ws \
  --program examples/p25_programme.xlsx --site examples/p25_site.yaml \
  --rulebook examples/rulebook_seed_draft.yaml --out my_ws/runs/p25 --variants 2
```

Each variant takes about the optimiser's time budget (`[optimizer] time_budget_s` in `my_ws/ale.toml`,
default 120 s; set it to 30 for quick tries). Outputs are written **on your machine** in `my_ws/runs/p25/` (not in the repository):

- `summary.md` — one line per variant: cost, number of hard-rule violations, circulation %;
- `variant_NN/preview.svg` — open in a web browser;
- `variant_NN/layout.dxf` — open in AutoCAD / LibreCAD / any DXF viewer;
- `variant_NN/report.md` — areas, violations, cost breakdown;
- `variant_NN/layout.json` — machine-readable layout.

Change `--seed` to get different variants.

## 4. Use your own program

```bash
ale program template --out my_programme.xlsx      # Excel template, French headers, drop-down lists
ale program check --program my_programme.xlsx --site examples/p25_site.yaml \
  --rulebook examples/rulebook_seed_draft.yaml    # validates and checks feasibility before generating
```

A site is a YAML file: `footprint` (outline points in metres, counter-clockwise), `north_angle_deg`,
`access_edge` (index of the edge with the entrance), `core_hint` (optional). See `p25_site.yaml`.

## Current limits (v1)

- Rectangular and L-shaped footprints only, one storey.
- Large programs (P60) still end with a few hard-rule violations, mostly offices without façade. This is
  being worked on (ticket Q.3).
- Command line only; a graphical interface is planned for v2.
