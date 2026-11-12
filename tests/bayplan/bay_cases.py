"""Cases A-F of Ticket M.4 (helpers; never imported as ``conftest``).

A, B, C go through ``run_stack`` + ``run_plans(planner="bay")``; E and F (a clean section, the
kernel called directly) are built here from a rectangle, one solid in the band and a programme.
``catalogue`` recomputes the shapes of RD 4.5 from the formulas (it does not import the planner).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent.parent
for sub in ("stack", "program"):
    if str(_TESTS / sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / sub))

import bar_case  # noqa: E402
import stack_case  # noqa: E402

from ale.config import AleConfig  # noqa: E402
from ale.contracts.models import CoreSpec, Program, SiteSpec  # noqa: E402
from ale.contracts.serialization import dump_yaml  # noqa: E402
from ale.parti.evaluate import neutral_rulebook  # noqa: E402
from ale.program import load_rulebook, prepare_input  # noqa: E402
from ale.program.models import PreparedInput  # noqa: E402
from ale.stack import StackResult, parse_building, parse_rules, run_stack  # noqa: E402
from ale.stack.floors import write_programme_xlsx  # noqa: E402
from ale.stack.grid import Rhythm  # noqa: E402
from ale.stack.plans import PlansResult, run_plans  # noqa: E402

WET = ("sanitary", "cleaning_room", "technical_room")
GROUND = AleConfig()
SKETCH = GROUND.model_copy(
    update={"area": GROUND.area.model_copy(update={"tol_down_pct": 10.0, "tol_up_pct": 10.0})}
)


# ------------------------------------------------------------------------------ A, B, C
def case_inputs(name: str) -> tuple[Program, dict[str, Any], dict[str, Any]]:
    """``(programme, building dict, rules dict)`` of case A (factor 1.3), B (1.7) or C (M.1)."""
    if name == "C":
        return stack_case.program(), stack_case.building_dict(), dict(stack_case.RULES)
    factor = 1.3 if name == "A" else bar_case.FACTOR
    rows = stack_case.rooms_list()
    for r in rows:
        if r["macro_zone"] != "SERVICES" and r["type"] in bar_case.SCALED:
            r["quantity"] = max(1, round(r["quantity"] * factor))
            if r["type"] == "open_office":
                r["target_area_m2"] = r["target_area_m2"] * factor
    return stack_case.program(rows), bar_case.building_dict(), dict(bar_case.RULES)


def write_case(name: str, d: Path) -> tuple[Path, Path, Path, Path]:
    """``(programme.xlsx, building.yaml, rules.yaml, rulebook.yaml)`` of case ``name``."""
    import yaml

    d.mkdir(parents=True, exist_ok=True)
    prog, bld, rules = case_inputs(name)
    p = stack_case.program_to_xlsx(prog, d / "programme.xlsx")
    b = stack_case.write_building(d / "building.yaml", bld)
    r = d / "rules.yaml"
    r.write_text(yaml.safe_dump(rules), encoding="utf-8")
    rb = d / "rulebook.yaml"
    rb.write_text(dump_yaml(neutral_rulebook(prog)), encoding="utf-8")
    return p, b, r, rb


def run_case(
    name: str, out: Path, planner: str = "bay"
) -> tuple[PlansResult, StackResult, Path, Program]:
    """Stack and plan case ``name`` into ``out``; ``(plans, stack, rulebook path, programme)``."""
    prog, bld, rules = case_inputs(name)
    rb = out / "rulebook.yaml"
    out.mkdir(parents=True, exist_ok=True)
    rb.write_text(dump_yaml(neutral_rulebook(prog)), encoding="utf-8")
    res = run_stack(prog, parse_building(bld), parse_rules(rules), strict_solids=True)
    pr, used = run_plans(res, rb, out, budget_s=1.0, planner=planner)
    return pr, used, rb, prog


def prepared_floor(out: Path, rb: Path, level: int) -> PreparedInput:
    d = out / f"floor_{level:02d}" / "plan"
    return prepare_input(d / "programme.xlsx", d / "site.yaml", rb, GROUND)


# ------------------------------------------------------------------------------- E and F
def rooms_e() -> list[dict[str, Any]]:
    r = stack_case.room
    return [
        r("AA01", "Bureau AA", "office", 12, qty=15, facade=True),
        r("AA02", "Reunion AA", "meeting_room", 24, qty=2, facade=True),
        r("AA03", "Plateau AA", "open_office", 150, facade=True),
        r("AA04", "Archives AA", "archive", 30, "SERVICES"),
        r("BB01", "Bureau BB", "office", 12, qty=15, facade=True),
        r("BB02", "Reunion BB", "meeting_room", 24, qty=2, facade=True),
        r("BB03", "Archives BB", "archive", 30, "SERVICES"),
        r("LOG01", "Stock", "storage", 20, "SERVICES"),
        r("LOG02", "Reprographie", "print_room", 20, "SERVICES"),
    ]


def rhythm_for(transposed: bool) -> Rhythm:
    """Bay 2.4 m (4 cells), bay lines on multiples of 2.4 m on the long axis."""
    return Rhythm(12, 12, 4, 4 if not transposed else 0, 0 if not transposed else 4, 0.0, 0.0)


def build_bar(
    d: Path,
    *,
    transposed: bool = False,
    length: float = 64.8,
    depth: float = 19.2,
    solids: tuple[tuple[float, float, float, float], ...] = ((24.0, 6.6, 16.8, 6.0),),
    rooms: list[dict[str, Any]] | None = None,
) -> tuple[PreparedInput, Any, Rhythm]:
    """A bar plate with solids (given along the long side: ``(u, v, du, dv)``), a programme and
    its rulebook, prepared; ``(prepared, rulebook, rhythm)``."""
    d.mkdir(parents=True, exist_ok=True)
    prog = stack_case.program(rooms or rooms_e())
    w, h = (depth, length) if transposed else (length, depth)
    cores = []
    for n, (u, v, du, dv) in enumerate(solids):
        rect = (v, u, dv, du) if transposed else (u, v, du, dv)
        cores.append(CoreSpec(id=f"S{n}", rect=rect, kind="core"))
    site = SiteSpec(
        footprint={"exterior": [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)], "holes": ()},
        north_angle_deg=0.0,
        access_edge=0,
        cores=tuple(cores),
    )
    (d / "site.yaml").write_text(dump_yaml(site), encoding="utf-8")
    write_programme_xlsx(prog, d / "programme.xlsx")
    (d / "rulebook.yaml").write_text(dump_yaml(neutral_rulebook(prog)), encoding="utf-8")
    prepared = prepare_input(d / "programme.xlsx", d / "site.yaml", d / "rulebook.yaml", GROUND)
    rb, _ = load_rulebook(d / "rulebook.yaml")
    return prepared, rb, rhythm_for(transposed)


# --------------------------------------------------------------- catalogue (RD 4.5, floats)
EPS = 1e-6


def window(target: float, pct: float = 10.0) -> tuple[float, float]:
    """Sketch window of a room: ``[T (1 - p), T + max(T p, 1.2)]`` in m2."""
    return target * (1 - pct / 100), target + max(target * pct / 100, 1.2)


def catalogue(
    target: float,
    facade: bool,
    *,
    min_width: float = 1.2,
    bay: float = 2.4,
    df: float = 4.8,
    c: float = 1.8,
    plate: float = 19.2,
    aspect: float = 2.0,
) -> dict[str, list[tuple[str, float, float, float]]]:
    """Admissible shapes ``(tag, width m, depth m, area m2)`` by kind (F, D, T, B, b) of a room,
    recomputed from RD 4.5: F ``k b x d_f`` (k a multiple of 0.5), D ``k b x (d_f + c + band)``,
    T ``k b x plate``, B ``w x band`` and b ``w x band/2`` (w a multiple of 0.6 m, at least 1.2 m,
    b only when the band is at least 4.8 m deep)."""
    band = plate - 2 * df - 2 * c
    lo, hi = window(target)

    def ok(w: float, d: float) -> bool:
        a = w * d
        return (
            lo - EPS <= a <= hi + EPS
            and max(w, d) / min(w, d) <= aspect + EPS
            and min(w, d) >= min_width - EPS
        )

    out: dict[str, list[tuple[str, float, float, float]]] = {k: [] for k in "FDTBb"}
    for n in range(1, 41):
        k = n / 2
        for kind, d in (("F", df), ("D", df + c + band), ("T", plate)):
            if ok(k * bay, d):
                out[kind].append((f"{kind}{k:g}", k * bay, d, k * bay * d))
    if not facade:
        for n in range(2, 60):
            w = round(0.6 * n, 6)
            if ok(w, band):
                out["B"].append((f"B{w:g}", w, band, w * band))
            if band >= 4.8 - EPS and ok(w, band / 2):
                out["b"].append((f"b{w:g}", w, band / 2, w * band / 2))
    return out


def no_shape(target: float, facade: bool, **kw: float) -> bool:
    """The room has no admissible shape at all (it is placed « à ajuster » or unplaced)."""
    cat = catalogue(target, facade, **kw)
    kinds = "FDT" if facade else "FDBb"
    return not any(cat[k] for k in kinds)


def fallback(
    target: float,
    facade: bool,
    *,
    min_width: float = 1.2,
    bay: float = 2.4,
    df: float = 4.8,
    c: float = 1.8,
    plate: float = 19.2,
    aspect: float = 2.0,
) -> tuple[str, float]:
    """``(tag, relative area deviation)`` of the aspect-legal shape of smallest deviation of a
    room without admissible shape (RD 4.5: 15 -> F1.5, 80 -> D3)."""
    band = plate - 2 * df - 2 * c
    shapes: list[tuple[float, str]] = []
    for n in range(1, 41):
        k = n / 2
        kinds = (("F", df), ("D", df + c + band), ("T", plate))
        for kind, d in kinds:
            if kind == "T" and not facade:
                continue
            w = k * bay
            if max(w, d) / min(w, d) <= aspect + EPS and min(w, d) >= min_width - EPS:
                shapes.append((abs(w * d - target) / target, f"{kind}{k:g}"))
    if not facade:
        for n in range(2, 60):
            w = round(0.6 * n, 6)
            for kind, d in (("B", band), ("b", band / 2)):
                if max(w, d) / min(w, d) <= aspect + EPS and min(w, d) >= min_width - EPS:
                    shapes.append((abs(w * d - target) / target, f"{kind}{w:g}"))
    dev, tag = min(shapes)
    return tag, dev
