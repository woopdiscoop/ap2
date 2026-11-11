"""Ticket G.3 evaluation G301..G309 (synthetic plot: the prototype's ground-floor case)."""

from __future__ import annotations

import filecmp
import math
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import case_helpers as case
import yaml
from shapely import LineString, Point, box
from shapely import Polygon as ShapelyPolygon

from ale.cli.commands.form import Candidate
from ale.contracts.models import Program, SiteSpec
from ale.contracts.serialization import load_yaml
from ale.form.grow import (
    CELL_M,
    CIRC_ID,
    COURT,
    PARTY,
    FormResult,
    grow_form,
    outside_cells_connected,
)
from ale.form.metrics import compute_metrics
from ale.form.outline import outline_from_cells
from ale.topology.cellgrow import CORE_CELL, FREE, OUTSIDE

REPO = Path(__file__).resolve().parents[2]


def _built(c: Candidate) -> set[tuple[int, int]]:
    r = c.result
    return {r.xy(i) for i in r.built_cells()}


def _connected(cells: set[tuple[int, int]]) -> bool:
    first = min(cells)
    seen, queue = {first}, deque([first])
    while queue:
        x, y = queue.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in cells and n not in seen:
                seen.add(n)
                queue.append(n)
    return len(seen) == len(cells)


def _street_connected(c: Candidate) -> bool:
    """Independent flood fill: every unbuilt, non-party cell reaches a cell outside the plot."""
    r = c.result
    free = {r.xy(i) for i, v in enumerate(r.owner) if v in (FREE, OUTSIDE, COURT)}
    streets = {r.xy(i) for i in range(len(r.owner)) if not r.in_plot[i] and r.owner[i] == OUTSIDE}
    streets |= {r.xy(i) for i in r.court_cells}  # the courtyard counts as outside
    seen, queue = set(streets), deque(streets)
    while queue:
        x, y = queue.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in free and n not in seen:
                seen.add(n)
                queue.append(n)
    return seen == free


# --------------------------------------------------------------------------------- G301
def test_g301_one_mass(candidates: list[Candidate]) -> None:
    site = case.site()
    ext = site.footprint.exterior
    segs = [LineString([ext[i], ext[(i + 1) % len(ext)]]) for i in range(len(ext))]
    assert site.setbacks is not None
    assert len(candidates) == 6
    for c in candidates:
        r = c.result
        assert _connected(_built(c)), f"candidate {c.k}: several pieces"
        assert _street_connected(c), f"candidate {c.k}: outside cut off"
        assert outside_cells_connected(r)
        for i, v in enumerate(r.owner):
            if v < 0:
                continue  # rooms only (cores may sit anywhere in the plot)
            cx, cy = r.xy(i)
            cell = box(
                r.origin[0] + cx * CELL_M,
                r.origin[1] + cy * CELL_M,
                r.origin[0] + (cx + 1) * CELL_M,
                r.origin[1] + (cy + 1) * CELL_M,
            )
            for k, seg in enumerate(segs):
                assert cell.distance(seg) >= site.setbacks[k] - 1e-9, (c.k, cx, cy, k)
            # beyond the party wall nothing is built (the plot is the limit)
            assert 0 <= cx < r.width and 0 <= cy < r.height


# --------------------------------------------------------------------------------- G302
def test_g302_areas(candidates: list[Candidate]) -> None:
    prog = case.program()
    expected = {iid: round(s.target_area_m2 / (CELL_M * CELL_M)) for iid, s in prog.instances()}
    core_cells = {i for _, cs in candidates[0].result.cores for i in cs}
    assert len(core_cells) == 5 * 6 + 5 * 5  # 3.0 x 3.6 m and 3.0 x 3.0 m in 0.6 m cells
    for c in candidates:
        counts = c.result.counts()
        short = [n for n, e in expected.items() if counts[n] < e]
        assert len(short) == c.metrics.short  # the shortfall is reported
        assert not short, (c.k, short)
        for n, e in expected.items():
            assert counts[n] >= e
        assert counts[CIRC_ID] >= c.result.need[CIRC_ID]
        for i in core_cells:
            assert c.result.owner[i] == CORE_CELL
        assert sum(v == CORE_CELL for v in c.result.owner) == len(core_cells)


# --------------------------------------------------------------------------------- G303
def test_g303_anchors(candidates: list[Candidate]) -> None:
    site = case.site()
    ent = Point(site.entrances[0].point)
    for c in candidates:
        r = c.result
        assert r.hall == "H01"
        hall = [i for i, v in enumerate(r.owner) if v == r.rooms.index("H01")]

        def gap(cells: list[int], r: FormResult = r) -> float:
            best = math.inf
            for i in cells:
                cx, cy = r.xy(i)
                b = box(
                    r.origin[0] + cx * CELL_M,
                    r.origin[1] + cy * CELL_M,
                    r.origin[0] + (cx + 1) * CELL_M,
                    r.origin[1] + (cy + 1) * CELL_M,
                )
                best = min(best, b.distance(ent))
            return best

        buildable = [i for i, b in enumerate(r.buildable) if b]
        # the hall holds the front-line cell nearest to the entrance (across the setback)
        assert gap(hall) <= gap(buildable) + 1e-9, c.k
        circ = len(r.rooms) - 1
        wp = r.wp
        for _, cells in r.cores:
            assert any(r.owner[n] == circ for i in cells for n in (i + 1, i - 1, i + wp, i - wp)), (
                c.k,
                "circulation misses a core",
            )


# --------------------------------------------------------------------------------- G304
def test_g304_courtyard(court_candidates: list[Candidate], candidates: list[Candidate]) -> None:
    assert all(c.metrics.courtyard == "none" for c in candidates)
    states = set()
    for c in court_candidates:
        r = c.result
        assert len(r.court_cells) == 19 * 19
        assert c.metrics.courtyard in ("open", "enclosed")
        assert c.metrics.courtyard_cells == 361
        assert all(r.owner[i] == COURT for i in r.court_cells)
        assert _connected(_built(c))
        assert _street_connected(c)
        # independent classification on the outline: the polygon has a hole around the court
        # exactly when the courtyard is enclosed
        poly = ShapelyPolygon(c.outline.polygons[0].exterior, c.outline.polygons[0].holes)
        cx, cy = r.xy(r.court_cells[0])
        centre = Point(r.origin[0] + (cx + 0.5) * CELL_M, r.origin[1] + (cy + 0.5) * CELL_M)
        in_hole = any(ShapelyPolygon(h).contains(centre) for h in c.outline.polygons[0].holes)
        assert not poly.contains(centre)
        touching = not in_hole
        assert c.metrics.courtyard == ("open" if touching else "enclosed")
        states.add(c.metrics.courtyard)
    assert states == {"open", "enclosed"}


# --------------------------------------------------------------------------------- G305
def test_g305_outline(candidates: list[Candidate], court_candidates: list[Candidate]) -> None:
    for c in [*candidates, *court_candidates]:
        r, o = c.result, c.outline
        assert len(o.polygons) == 1
        ox, oy = r.origin
        verts = 0
        for poly in o.polygons:
            for ring in (poly.exterior, *poly.holes):
                n = len(ring)
                assert n >= 4
                verts += n
                for k in range(n):
                    a, b = ring[k], ring[(k + 1) % n]
                    assert (a[0] == b[0]) != (a[1] == b[1]), "edge neither horizontal nor vertical"
                    for coord, o0 in ((a[0], ox), (a[1], oy)):
                        q = (coord - o0) / CELL_M
                        assert abs(q - round(q)) < 1e-6
                assert len(set(ring)) == n
        assert verts == o.vertices_after > 0
        assert o.vertices_before > 0
        built = _built(c)
        assert abs(o.area() - len(o.cells) * CELL_M**2) < 1e-6
        assert abs(o.area() - len(built) * CELL_M**2) <= 0.01 * len(built) * CELL_M**2
        assert abs(len(o.cells) - len(built)) <= o.cells_filled + o.cells_cut
        assert o.cells_filled >= 0 and o.cells_cut >= 0
        # no notch narrower than 2 cells is left in the simplified cells
        cells = set(o.cells)
        xs = [p[0] for p in cells]
        ys = [p[1] for p in cells]
        for x in range(min(xs) - 1, max(xs) + 2):
            for y in range(min(ys) - 1, max(ys) + 2):
                if (x, y) in cells:
                    continue
                assert not ((x - 1, y) in cells and (x + 1, y) in cells), (c.k, x, y)
                assert not ((x, y - 1) in cells and (x, y + 1) in cells), (c.k, x, y)
        poly = ShapelyPolygon(o.polygons[0].exterior, o.polygons[0].holes)
        assert poly.is_valid
        assert abs(poly.area - o.area()) < 1e-6


def test_g305_notches_are_removed() -> None:
    """A one-cell-wide slit is filled, a two-cell-wide one is kept."""
    mass = {(x, y) for x in range(10) for y in range(6)}
    slit1 = mass - {(5, y) for y in range(2, 6)}  # open at the top, 1 cell wide
    slit2 = mass - {(x, y) for x in (5, 6) for y in range(2, 6)}  # 2 cells wide
    o1 = outline_from_cells(slit1)
    assert o1.cells == frozenset(mass)
    assert o1.cells_filled == 4
    assert o1.vertices_before > o1.vertices_after == 4
    o2 = outline_from_cells(slit2)
    assert o2.cells == frozenset(slit2)
    assert o2.cells_filled == o2.cells_cut == 0


# --------------------------------------------------------------------------------- G306
def test_g306_yaml(cli_out: Path) -> None:
    site = case.site()
    for k in range(1, 7):
        text = (cli_out / f"form_{k:02d}.yaml").read_text(encoding="utf-8")
        spec = load_yaml(SiteSpec, text)
        assert spec.mode == "footprint"
        assert spec.setbacks is None and spec.party_edges == ()
        assert spec.cores == site.cores
        assert len(spec.entrances) == 1 and spec.entrances[0].main
        assert spec.entrances[0].label == site.entrances[0].label
        poly = ShapelyPolygon(spec.footprint.exterior, spec.footprint.holes)
        assert poly.boundary.distance(Point(spec.entrances[0].point)) < 1e-6
        for core in spec.cores:
            x, y, w, h = core.rect
            assert poly.buffer(1e-6).covers(box(x, y, x + w, y + h))
        n = len(spec.footprint.exterior)
        assert 0 <= spec.access_edge < n


# --------------------------------------------------------------------------------- G307
def _run_cli(inputs: tuple[Path, Path], out: Path, *extra: str) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "ale",
            "form",
            "--program",
            str(inputs[0]),
            "--site",
            str(inputs[1]),
            "--out",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_g307_deterministic(inputs: tuple[Path, Path], tmp_path: Path, cli_out: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _run_cli(inputs, a)
    _run_cli(inputs, b)
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir()) == sorted(p.name for p in cli_out.iterdir())
    assert len(names) == 13  # 6 x (svg, yaml) + forms.md
    for n in names:
        assert (a / n).read_bytes() == (b / n).read_bytes(), n
        assert filecmp.cmp(a / n, cli_out / n, shallow=False), n
    outlines = {
        tuple(
            map(
                tuple,
                yaml.safe_load((a / f"form_{k:02d}.yaml").read_text())["footprint"]["exterior"],
            )
        )
        for k in range(1, 7)
    }
    assert len(outlines) >= 3


# --------------------------------------------------------------------------------- G308
def _parse_ranking(md: str) -> list[tuple[int, str, list[str]]]:
    rows = []
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0].isdigit():
            rows.append((int(cells[0]), cells[1], cells[2:]))
    return rows


def test_g308_ranking(cli_out: Path, candidates: list[Candidate]) -> None:
    rows = _parse_ranking((cli_out / "forms.md").read_text(encoding="utf-8"))
    assert [r[0] for r in rows] == list(range(1, 7))
    assert sorted(r[1] for r in rows) == [f"form_{k:02d}" for k in range(1, 7)]
    keys = []
    for _rank, name, vals in rows:
        c = candidates[int(name[-2:]) - 1]
        r = c.result
        # recompute from the files and the cell grid, independently of ale.form.metrics
        spec = load_yaml(SiteSpec, (cli_out / f"{name}.yaml").read_text(encoding="utf-8"))
        poly = ShapelyPolygon(spec.footprint.exterior, spec.footprint.holes)
        counts = r.counts()
        short = sum(counts[n] < r.need[n] for n in r.rooms if n != CIRC_ID)
        circ = len(r.rooms) - 1
        wp = r.wp
        missing = off = 0
        for k, n in enumerate(r.rooms[:-1]):
            mine = [i for i, v in enumerate(r.owner) if v == k]
            ring = [m for i in mine for m in (i + 1, i - 1, i + wp, i - wp)]
            if r.needs_facade[n] and not any(r.owner[m] in (FREE, OUTSIDE, COURT) for m in ring):
                missing += 1
            if not any(r.owner[m] == circ for m in ring):
                off += 1
        vertices = len(spec.footprint.exterior) + sum(len(h) for h in spec.footprint.holes)
        compact = poly.length / (4 * math.sqrt(poly.area))
        assert (vals[0], vals[1], vals[2], vals[3]) == (
            str(short),
            str(missing),
            str(off),
            str(vertices),
        )
        assert float(vals[4]) == round(compact, 3)
        assert float(vals[5]) == round(poly.area, 1)
        built = sum(v >= 0 or v == CORE_CELL for v in r.owner)
        assert float(vals[7]) == round(built / sum(r.buildable), 3)
        keys.append((short, missing, off, vertices, round(compact, 9)))
    assert keys == sorted(keys)
    # facade length: outline edges facing unbuilt, non-party cells
    c = candidates[0]
    r = c.result
    cells = set(c.outline.cells)
    facade = sum(
        (x + dx, y + dy) not in cells and r.owner[r.idx(x + dx, y + dy)] in (FREE, OUTSIDE, COURT)
        for x, y in cells
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
    )
    assert math.isclose(c.metrics.facade_m, facade * CELL_M)
    assert PARTY not in (FREE, OUTSIDE, COURT)


# --------------------------------------------------------------------------------- G309
def test_g309_gates(program_25: Program) -> None:
    """Lock check and the speed of a P25-size case; ruff, mypy and coverage are run as gates."""
    done = subprocess.run(
        [sys.executable, "-m", "ale.contracts.lock", "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    plot = case.site(
        footprint={"exterior": [[0, 0], [40, 0], [40, 30], [0, 30]], "holes": []},
        setbacks=[3.0, 3.0, 3.0, 3.0],
        party_edges=[],
        cores=[],
        entrances=[{"point": [20.0, 0.0], "main": True}],
    )
    for k in range(1, 4):
        start = time.perf_counter()
        res = grow_form(program_25, plot, seed=k)
        outline = outline_from_cells({res.xy(i) for i in res.built_cells()}, res.origin, CELL_M)
        metrics = compute_metrics(res, outline)
        elapsed = time.perf_counter() - start
        assert elapsed <= 10.0, (k, elapsed)
        assert metrics.rooms == 25
        assert metrics.short == 0
