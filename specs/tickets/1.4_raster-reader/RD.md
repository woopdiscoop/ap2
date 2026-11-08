# Ticket 1.4 — Raster reader (classical CV, v1) · Requirements
> **Worker brief.** Context = this file, `eval.md`, the contracts (`src/ale/contracts/`: `PlanGeometry`, `Wall`, `Opening`, `LabelledPolygon`, `TextItem`, `Polygon`, `LineString`, enums, `taxonomy`), `ale.guards`, `ale.config`, test helpers. **Library only** — no CLI wiring (a later integration ticket wires `ale extract`/`ale review`). Do not modify contracts or other packages. All loops bounded; public functions never raise on bad input (problems → warnings).
## Files
`src/ale/raster/{__init__,read,preprocess,walls,rooms,openings}.py`, `tests/raster/**`, `specs/tickets/1.4_raster-reader/eval_report.md`. Dependencies: opencv-python-headless + Pillow (extra `raster`), numpy, shapely. No ML model in v1 (a CubiCasa5K variant may be added later behind the same API).
## API
`read_raster(image: Path | numpy array, *, source_sha256, page=0, source_kind=RASTER, config) -> RasterReadResult(plans, warnings, plan_score)`; also `rasterize_pdf_page(path, page, dpi) -> numpy array` (PyMuPDF, for PDF_SCANNED; extra `pdf`).
## Pipeline
1. **Preprocess**: grayscale; deskew (Hough dominant angle within ±10°, rotate if |angle| > 0.3°); denoise (median 3); binarise (Otsu; adaptive if background non-uniform); crop to the largest dark-content bbox + 2 % margin.
2. **Walls**: morphological opening with horizontal and vertical line kernels (length ≥ 2 % of the short image side); thickness from distance transform; wall mask = union; skeleton → centreline segments (merge collinear, min length 1.5 % of short side) → `Wall(centerline, thickness)`. Only axis-parallel walls in v1 (others warned).
3. **Rooms**: closing of the wall mask by the median wall thickness to seal door gaps; connected components of the free space; drop the background component touching the border and components < 0.2 % of image area; contour → simplified polygon (Douglas–Peucker 1 % of perimeter) → `LabelledPolygon` (unlabelled).
4. **Openings**: gaps in wall lines of length 0.5–1.5 × (median gap) bridged in step 3 → `Opening(DOOR)` with `width_native` = gap px.
5. Native units = pixels, frame `Y_DOWN`, scale UNKNOWN (1.6 decides). `plan_score` = documented formula (wall pixels share, room count).
