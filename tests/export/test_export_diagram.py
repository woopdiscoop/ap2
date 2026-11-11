"""Ticket R.9 eval R9-06: the SVG of the cell diagram."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_TOPOLOGY_TESTS = Path(__file__).resolve().parent.parent / "topology"
if str(_TOPOLOGY_TESTS) not in sys.path:
    sys.path.insert(0, str(_TOPOLOGY_TESTS))

import pytest  # noqa: E402
from cellgrow_helpers import anchor_prepared  # noqa: E402
from topology_helpers import load_test_rulebook  # noqa: E402

from ale.config import AleConfig  # noqa: E402
from ale.export.diagram import PALETTE, diagram_svg, write_diagram_svg  # noqa: E402
from ale.topology.cellgrow import CellDiagram, grow  # noqa: E402

NS = {"s": "http://www.w3.org/2000/svg"}


@pytest.fixture(scope="module")
def diagram(tmp_path_factory: pytest.TempPathFactory) -> CellDiagram:
    prep = anchor_prepared(tmp_path_factory.mktemp("diagram"))
    return grow(prep, load_test_rulebook(), AleConfig())


def test_R9_06_svg(diagram: CellDiagram, tmp_path: Path) -> None:
    text = diagram_svg(diagram)
    root = ET.fromstring(text)  # well-formed XML
    assert root.tag.endswith("svg")
    rects = root.findall("s:rect", NS)
    fills = {r.get("fill") for r in rects}
    # one colour per room type (and only per type)
    types = sorted(set(diagram.types.values()))
    assert len(types) >= 5
    colour_of = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(types)}
    assert set(colour_of.values()) <= fills
    for room, t in diagram.types.items():
        for x, y in diagram.cells[room]:
            cell = [r for r in rects if r.get("x") == str(x) and r.get("y") == str(-y - 1)]
            assert [c.get("fill") for c in cell] == [colour_of[t]]
    sanitary = {r for r, t in diagram.types.items() if t == "sanitary"}
    assert len(sanitary) == 2  # two rooms of one type, one colour
    # cores hatched
    assert "core-hatch" in text
    hatched = [r for r in rects if r.get("fill") == "url(#core-hatch)"]
    assert len(hatched) == len(diagram.cores) > 0
    # entrance marked, labels present
    circles = root.findall("s:circle", NS)
    assert [c.get("id") for c in circles] == ["entrance"]
    labels = {t.text for t in root.findall("s:text", NS)}
    assert labels == set(diagram.rooms)
    # deterministic bytes, file written as UTF-8 / LF
    assert diagram_svg(diagram) == text
    out = write_diagram_svg(diagram, tmp_path / "diagram.svg")
    assert out.read_bytes() == text.encode("utf-8")
    assert b"\r" not in out.read_bytes()


def test_R9_06_no_entrance_no_core(diagram: CellDiagram) -> None:
    bare = CellDiagram(
        step=diagram.step,
        module_m=diagram.module_m,
        width=diagram.width,
        height=diagram.height,
        owner=diagram.owner,
        rooms=diagram.rooms,
        types=diagram.types,
        targets=diagram.targets,
        cells={r: () for r in diagram.rooms},
        cores=(),
        entrance=None,
        checks=diagram.checks,
    )
    root = ET.fromstring(diagram_svg(bare))
    assert root.findall("s:circle", NS) == []
    assert root.findall("s:text", NS) == []
