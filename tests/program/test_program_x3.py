"""Ticket X.3 (X301-X304): courtyards at intake, façade estimate for N pieces."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
from fixtures import load_program
from program_helpers import program_to_xlsx, write_site_yaml
from typer.testing import CliRunner

from ale.cli import app
from ale.config import AleConfig
from ale.contracts.footprint import decompose_footprint
from ale.contracts.geometry import ModulePolygon
from ale.contracts.models import GridSpec, Layout
from ale.geometry.checks import check_layout
from ale.logging_setup import shutdown_logging
from ale.program.feasibility import facade_usable_mm
from ale.program.models import InputError
from ale.program.prepare import check_inputs, prepare_input
from ale.program.site import module_perimeter_mm, read_site, to_module_footprint

_GEOMETRY = Path(__file__).resolve().parent.parent / "geometry"
if str(_GEOMETRY) not in sys.path:
    sys.path.insert(0, str(_GEOMETRY))

from g1_shapes import p25  # noqa: E402

RULEBOOK_TEST = Path(__file__).resolve().parent / "data" / "rulebook_test.yaml"
GRID = GridSpec()

EXT: list[list[float]] = [[0, 0], [24, 0], [24, 24], [0, 24]]
HOLE: list[list[float]] = [[8, 8], [16, 8], [16, 16], [8, 16]]


def _site(tmp: Path, footprint: Any, name: str = "site.yaml") -> Path:
    return write_site_yaml(tmp / name, {"footprint": footprint})


def _read(tmp: Path, footprint: Any, name: str = "site.yaml") -> Any:
    return read_site(_site(tmp, footprint, name))


def _hole_errors(tmp: Path, holes: list[Any]) -> list[str]:
    site, issues = _read(tmp, {"exterior": EXT, "holes": holes})
    assert site is None
    return [i.message for i in issues]


# ------------------------------------------------------------------------------ X301
def test_X301_holes_intake(tmp_path: Path) -> None:
    site, issues = _read(tmp_path, {"exterior": EXT, "holes": [HOLE]})
    assert issues == () and site is not None
    assert len(site.footprint.holes) == 1
    fp = to_module_footprint(site, GRID)
    assert fp.polygon.exterior == ((0, 0), (240, 0), (240, 240), (0, 240))
    assert fp.polygon.holes == (((80, 80), (80, 160), (160, 160), (160, 80)),)  # clockwise
    assert fp.polygon.area_cells() == 240 * 240 - 80 * 80
    assert fp.sliver_loss_m2 == 0.0
    # counter-clockwise input is normalised to clockwise
    ccw = [list(p) for p in reversed(HOLE)]
    site2, _ = _read(tmp_path, {"exterior": EXT, "holes": [ccw]}, "b.yaml")
    assert site2 is not None and site2.footprint.holes == site.footprint.holes
    # a plain list still works
    plain, issues = _read(tmp_path, EXT, "c.yaml")
    assert issues == () and plain is not None and plain.footprint.holes == ()

    far = [[30, 30], [34, 30], [34, 34], [30, 34]]
    bad: dict[str, tuple[list[Any], str]] = {
        "outside": ([HOLE, far], "Cour intérieure 1"),
        "crossing": ([[[20, 8], [28, 8], [28, 16], [20, 16]]], "Cour intérieure 0"),
        "touching": ([[[0, 8], [4, 8], [4, 16], [0, 16]]], "Cour intérieure 0"),
        "overlap": ([HOLE, [[12, 12], [20, 12], [20, 20], [12, 20]]], "Cour intérieure 1"),
        "diagonal": ([[[8, 8], [16, 8], [16, 16], [10, 18]]], "Cour intérieure 0"),
        "degenerate": ([[[8, 8], [16, 8], [20, 8]]], "Cour intérieure 0"),
    }
    for name, (holes, expect) in bad.items():
        messages = _hole_errors(tmp_path, holes)
        assert any(expect in m for m in messages), (name, messages)
    assert any("non orthogonale" in m for m in _hole_errors(tmp_path, bad["diagonal"][0]))
    # schema errors
    bad_site, issues = _read(tmp_path, {"exterior": EXT, "x": 1}, "d.yaml")
    assert bad_site is None and "Clé inconnue" in issues[0].message
    bad_site, issues = _read(tmp_path, {"holes": []}, "e.yaml")
    assert bad_site is None and "exterior" in issues[0].message
    bad_site, issues = _read(tmp_path, {"exterior": EXT, "holes": 3}, "f.yaml")
    assert bad_site is None and "holes" in issues[0].message
    bad_site, issues = _read(tmp_path, {"exterior": EXT, "holes": [[[1, 1]]]}, "g.yaml")
    assert bad_site is None and "holes[0]" in issues[0].message

    # too small: < 3 x 3 modules, checked at the grid (hole 1 is 2 x 2 modules once snapped outward)
    for size in (0.2, 0.15):
        small = [[18, 18], [18, 18 + size], [18 + size, 18 + size], [18 + size, 18]]
        s, _ = _read(tmp_path, {"exterior": EXT, "holes": [HOLE, small]}, "h.yaml")
        assert s is not None
        with pytest.raises(InputError) as exc:
            to_module_footprint(s, GRID)
        assert "Cour intérieure 1" in exc.value.issues[0].message
        assert exc.value.issues[0].code == "E_SITE_TOO_SMALL"
    # an off-grid hole grows outward: 3.0 modules wide off-grid becomes 4
    ok = [[10.05, 10.05], [10.05, 10.35], [10.35, 10.35], [10.35, 10.05]]
    s, _ = _read(tmp_path, {"exterior": EXT, "holes": [ok]}, "i.yaml")
    assert s is not None
    fp2 = to_module_footprint(s, GRID)
    assert fp2.polygon.holes == (((100, 100), (100, 104), (104, 104), (104, 100)),)
    assert fp2.sliver_loss_m2 > 0
    # holes that merge once snapped are refused
    tight = [[16.01, 8], [16.01, 16], [20, 16], [20, 8]]
    s, _ = _read(tmp_path, {"exterior": EXT, "holes": [HOLE, tight]}, "j.yaml")
    assert s is not None
    with pytest.raises(InputError):
        to_module_footprint(s, GRID)


# ------------------------------------------------------------------------------ X302
def _poly(*pts: tuple[int, int], holes: Any = ()) -> ModulePolygon:
    return ModulePolygon(exterior=pts, holes=holes)


U = _poly((0, 0), (30, 0), (30, 24), (20, 24), (20, 10), (10, 10), (10, 24), (0, 24))
COMB = _poly(
    (0, 0), (36, 0), (36, 24), (28, 24), (28, 10), (20, 10),
    (20, 24), (16, 24), (16, 10), (8, 10), (8, 24), (0, 24),
)  # fmt: skip
RING = _poly((0, 0), (30, 0), (30, 30), (0, 30), holes=(((10, 10), (10, 20), (20, 20), (20, 10)),))
S_SPINE = 2


def test_X302_facade_n() -> None:
    # Hand computation, spine width s = 2, one band per piece (n0 = 1), module 100 mm.
    # A piece counts its two edges parallel to the spine, minus the parts on any junction
    # cut, minus s per exterior short edge (an edge on a cut is not exterior).
    #
    # U: left arm 10x24 | base 20x10 | right arm 10x14, cuts x=10 (y 0-10), y=10 (x 20-30).
    #   arm: 24 + (24-10) - 2*2 = 34 ; base: 20 + (20-10) - 1*2 = 28 ; arm: 14+14 - 1*2 = 26
    assert facade_usable_mm(U, [], S_SPINE, 100) == 88 * 100
    # comb: base 36x10 with 3 fingers 8, 4, 8 wide: 36 + (36-20) - 2*2 = 48 ; fingers
    #   28 - 2 = 26 each.
    assert facade_usable_mm(COMB, [], S_SPINE, 100) == (48 + 3 * 26) * 100
    # ring 30x30, courtyard 10x10 (courtyard faces are façade):
    #   top bar 30x10: 30 + (30-20) - 2*2 = 36 ; left column 10x20: 20 + (20-10) - 1*2 = 28 ;
    #   bottom 10x10: 10 + 10 - 1*2 = 18 (its right side is an open contact, not a junction) ;
    #   right column: 20 + 20 - 1*2 = 38.
    assert facade_usable_mm(RING, [], S_SPINE, 100) == 120 * 100
    assert len(decompose_footprint(RING).junctions) == 3
    # perimeter includes the courtyard: 120 + 40 modules
    assert module_perimeter_mm(RING, GRID) == 160 * 100
    assert module_perimeter_mm(_poly((0, 0), (30, 0), (30, 30), (0, 30)), GRID) == 120 * 100


def _legacy_usable(polygon: ModulePolygon, s: int, module: int) -> int:
    """The pre-X.3 estimate (single legacy ``cut``), for ``targets = []`` (n0 = 1)."""
    from ale.program.feasibility import _overlap, _piece_edges

    fp = decompose_footprint(polygon)
    total = 0
    for piece in fp.pieces:
        long_edges, short_edges = _piece_edges(piece)
        for (ax, ay), (bx, by) in long_edges:
            total += abs(bx - ax) + abs(by - ay) - _overlap(((ax, ay), (bx, by)), fp.cut)
        total -= s * sum(1 for seg in short_edges if _overlap(seg, fp.cut) == 0)
    return max(0, total) * module


def test_X302_rectangles_and_l_unchanged() -> None:
    shapes = [
        _poly((0, 0), (24, 0), (24, 20), (0, 20)),
        _poly((0, 0), (24, 0), (24, 10), (12, 10), (12, 20), (0, 20)),
        _poly((0, 0), (12, 0), (12, 10), (24, 10), (24, 20), (0, 20)),
        _poly((0, 0), (24, 0), (24, 20), (12, 20), (12, 10), (0, 10)),
        _poly((12, 0), (24, 0), (24, 20), (0, 20), (0, 10), (12, 10)),
    ]
    for poly in shapes:
        assert facade_usable_mm(poly, [], 2, 100) == _legacy_usable(poly, 2, 100)
    # byte-identical feasibility reports (digests computed at the base commit c3f8b33)
    rect = ((0, 0), (240, 0), (240, 200), (0, 200))
    ell = ((0, 0), (240, 0), (240, 100), (120, 100), (120, 200), (0, 200))
    digests = {
        name: hashlib.sha256(p25(pts).feasibility.model_dump_json().encode()).hexdigest()[:16]
        for name, pts in (("rect", rect), ("L", ell))
    }
    assert digests == {"rect": "1ded6e18cb96c834", "L": "9d1be35f679ec01b"}


# ------------------------------------------------------------------------------ X303
def _runner() -> CliRunner:
    try:  # click < 8.2
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


@pytest.mark.timeout(240)
def test_X303_end_to_end(tmp_path: Path) -> None:
    xlsx = program_to_xlsx(load_program("program_25"), tmp_path / "programme.xlsx")
    site = _site(tmp_path, {"exterior": EXT, "holes": [HOLE]})
    check = check_inputs(xlsx, site, RULEBOOK_TEST, AleConfig())
    assert check.errors == [] and check.feasibility is not None
    assert check.structure == (4, 3, 1)
    assert check.feasibility.perimeter_m == 96 + 32

    runner = _runner()
    try:
        res = runner.invoke(
            app,
            [
                *("program", "check", "--program", str(xlsx), "--site", str(site)),
                *("--rulebook", str(RULEBOOK_TEST)),
            ],
        )
        assert res.exit_code == 0, res.output
        assert "Emprise : 4 pièces, 3 jonctions, 1 cours intérieures" in res.stdout
        ws = tmp_path / "ws"
        assert runner.invoke(app, ["init", "--workspace", str(ws)]).exit_code == 0
        toml = ws / "ale.toml"
        text = toml.read_text(encoding="utf-8")
        toml.write_text(text.replace("time_budget_s = 120.0", "time_budget_s = 10.0"))
        out = tmp_path / "out"
        res = runner.invoke(
            app,
            [
                "generate",
                *("--program", str(xlsx), "--site", str(site)),
                *("--rulebook", str(RULEBOOK_TEST), "--out", str(out), "--seed", "3"),
                *("--workspace", str(ws)),
            ],
        )
    finally:
        shutdown_logging()
    assert res.exit_code == 0, res.output + res.stderr
    layout = Layout.model_validate_json((out / "variant_01" / "layout.json").read_text("utf-8"))
    assert layout.footprint.holes == (((80, 80), (80, 160), (160, 160), (160, 80)),)
    prepared = prepare_input(xlsx, site, RULEBOOK_TEST, AleConfig())
    assert check_layout(layout, prepared, AleConfig()) == ()
    covered = sum(r.rect.area_cells() for r in (*layout.rooms, *layout.circulation))
    assert covered == layout.footprint.area_cells()


# ------------------------------------------------------------------------------ X304
def test_X304_gates() -> None:
    """The gates (ruff, format, mypy strict, lock --check, coverage >= 90 % of the touched
    modules, whole suite) are run for the evaluation report; the cheap invariant here: a
    hole-free site keeps its feasibility report (see X302) and serialises without holes."""
    fp = to_module_footprint(read_site_inline(), GRID)
    assert "holes" not in fp.polygon.model_dump(mode="json")


def read_site_inline() -> Any:
    from ale.program.site import site_from_mapping

    site, issues = site_from_mapping({"footprint": EXT}, Path())
    assert issues == ()
    return site
