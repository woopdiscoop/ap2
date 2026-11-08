# Ticket 1.5 — Semantic labelling · Requirements
> **Worker brief.** Context = this file, `eval.md`, the contracts (`src/ale/contracts/`: `PlanGeometry`, `Wall`, `Opening`, `LabelledPolygon`, `TextItem`, `Polygon`, `LineString`, enums, `taxonomy`), `ale.guards`, `ale.config`, test helpers. **Library only** — no CLI wiring (a later integration ticket wires `ale extract`/`ale review`). Do not modify contracts or other packages. All loops bounded; public functions never raise on bad input (problems → warnings).
## Files
`src/ale/labels/{__init__,label,provider,cache,bbox}.py`, `tests/labels/**`, `specs/tickets/1.5_semantic-labelling/eval_report.md`.
## Priority
CAD_TEXT / CAD_ZONE → PDF_TEXT → VLM → MANUAL. `label_plan(plan, *, image: bytes | None, provider: VlmProvider | None, cache: VlmCache, config) -> LabelResult(plan, api_calls, warnings)`: rooms already typed by text are kept; text labelling is re-applied to untyped rooms from `plan.texts` (TextItem inside polygon → `normalize_label`); remaining untyped rooms go to the VLM **only if** a provider is given and `vlm.provider` is set; else they stay untyped.
## VLM interface (provider-agnostic; the real provider is decision O-3, not implemented here)
```python
class VlmRoom(BaseModel): label: str; bbox: tuple[int,int,int,int]; confidence: float   # [ymin, xmin, ymax, xmax] normalised 0–1000
class VlmResponse(BaseModel): rooms: tuple[VlmRoom, ...]
class VlmProvider(Protocol):
    model_id: str
    def label_image(self, image_png: bytes, prompt: str, *, temperature: float) -> str   # raw text, expected JSON
```
- Prompt (`PROMPT_VERSION = "v1"`, French + English, lists the allowed type keys/labels from the taxonomy) asks for JSON `{"rooms":[{"label","bbox","confidence"}]}`.
- Temperature from config (must be 0). Response parsed into `VlmResponse`; invalid → **one** retry with a repair instruction, then failure (rooms stay untyped, warning).
- `bbox.py`: the **only** conversion between the normalised 0–1000 `[ymin,xmin,ymax,xmax]` and plan native coordinates (given the image size and the plan's native extent).
- Matching VLM rooms to polygons: by overlap area (bbox ∩ polygon / bbox area ≥ 0.3), one-to-one via Hungarian (`scipy.optimize.linear_sum_assignment` if available, else a deterministic greedy fallback); label → `normalize_label` → type (unknown → `"unknown"`), `label_source VLM`, confidence = VLM confidence × overlap.
- **Cache** (`cache.py`): directory `workspace/cache/vlm/`, key = sha256(`source_sha256`, page, plan_index, PROMPT_VERSION, model_id, sha256(image)); stores the raw response; a cached call makes 0 provider calls.
