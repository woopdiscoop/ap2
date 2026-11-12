"""Tests M202-M206 and M208 (Ticket M.2): the exact-plan engine around fixed solids.

M202 intake (cores become solids), M203 façade rules ignore solid edges, M204 generation around
a central core, M205 the new hard rule (a solid enclosed by rooms), M206 outputs without cores
are byte-identical to the base commit ``62cade3``, M208 exports draw solids and fixed rooms.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

_TESTS = Path(__file__).resolve().parent.parent
for _sub in ("program", "geometry", "."):
    if str(_TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(_TESTS / _sub))

from fixtures import DATA_DIR, FIXTURE_PAIRS, load_program  # noqa: E402
from geometry_helpers import load_test_rulebook, prepared_from, room  # noqa: E402
from program_helpers import (  # noqa: E402
    RULEBOOK_TEST,
    program_to_xlsx,
    site_to_yaml,
    write_rulebook,
)

from ale.config import AleConfig  # noqa: E402
from ale.contracts.geometry import ModulePolygon, ModuleRect, Polygon  # noqa: E402
from ale.contracts.models import (  # noqa: E402
    CoreSpec,
    GridSpec,
    Layout,
    PlacedRoom,
    Program,
    SiteSpec,
)
from ale.contracts.serialization import canonical_json  # noqa: E402
from ale.geometry.checks import check_layout, exterior_contacts, solid_contact  # noqa: E402
from ale.geometry.evaluate import evaluate, facade_depth  # noqa: E402
from ale.program import load_rulebook, prepare_input  # noqa: E402
from ale.program.models import InputError, PreparedInput  # noqa: E402
from ale.program.site import solid_labels, to_module_footprint  # noqa: E402

RECT24 = ((0.0, 0.0), (24.0, 0.0), (24.0, 18.0), (0.0, 18.0))


def site_with(cores: tuple[CoreSpec, ...], ring: Any = RECT24) -> SiteSpec:
    return SiteSpec(
        footprint=Polygon(exterior=ring), north_angle_deg=0.0, access_edge=0, cores=cores
    )


def core(cid: str, x: float, y: float, w: float, h: float) -> CoreSpec:
    return CoreSpec(id=cid, rect=(x, y, w, h), kind="core")


# ------------------------------------------------------------------------------------ M202
def test_M202_core_becomes_solid_snapped_outward() -> None:
    fp = to_module_footprint(
        site_with((core("C1", 10.05, 7.05, 3.0, 3.0),)), GridSpec(module_mm=100)
    )
    assert fp.polygon.solids == (((100, 70), (100, 101), (131, 101), (131, 70)),)
    assert fp.polygon.area_cells() == 240 * 180 - 31 * 31
    coarse = to_module_footprint(
        site_with((core("C1", 10.0, 7.0, 3.0, 3.0),)), GridSpec(module_mm=600)
    )
    # x: floor(10 / 0.6) = 16, ceil(13 / 0.6) = 22; y: floor(7 / 0.6) = 11, ceil(10 / 0.6) = 17
    assert coarse.polygon.solids == (((16, 11), (16, 17), (22, 17), (22, 11)),)
    assert solid_labels(
        site_with((core("C1", 10.0, 7.0, 3.0, 3.0),)), coarse, GridSpec(module_mm=600)
    ) == ("C1",)


def test_M202_touching_cores_merge_into_one_solid() -> None:
    site = site_with((core("A", 9.0, 6.0, 3.0, 3.0), core("B", 12.0, 6.0, 3.0, 6.0)))
    fp = to_module_footprint(site, GridSpec(module_mm=100))
    assert len(fp.polygon.solids) == 1
    assert fp.polygon.solids[0] == (
        (90, 60),
        (90, 90),
        (120, 90),
        (120, 120),
        (150, 120),
        (150, 60),
    )
    assert solid_labels(site, fp, GridSpec(module_mm=100)) == ("A+B",)


def test_M202_core_touching_the_outline() -> None:
    site = site_with((core("C1", 0.0, 6.0, 3.0, 3.0),))
    grid = GridSpec(module_mm=100)
    with pytest.raises(InputError) as exc:
        to_module_footprint(site, grid, strict_cores=True)
    assert exc.value.issues[0].code == "E_SITE_INVALID"
    assert "Noyau" in exc.value.issues[0].message
    # callers that only read ``SiteSpec.cores`` themselves (M.1) keep working: no solid
    assert to_module_footprint(site, grid).polygon.solids == ()


def test_M202_sites_without_cores_unchanged() -> None:
    site = site_with(())
    fp = to_module_footprint(site, GridSpec(module_mm=100))
    assert fp.polygon.solids == ()
    assert fp.polygon.area_cells() == 240 * 180
    assert "solids" not in fp.polygon.model_dump()
    assert fp.sliver_loss_m2 == 0.0


def test_M202_prepare_input_uses_cores(tmp_path: Path) -> None:
    prog = load_program("program_25")
    site = site_with((core("C1", 10.8, 7.2, 3.0, 3.6),))
    xlsx = program_to_xlsx(prog, tmp_path / "p.xlsx")
    prepared = prepare_input(
        xlsx, site_to_yaml(site, tmp_path / "s.yaml"), RULEBOOK_TEST, AleConfig()
    )
    assert len(prepared.footprint.polygon.solids) == 1
    bad = site_with((core("C1", 0.0, 6.0, 3.0, 3.0),))
    with pytest.raises(InputError):
        prepare_input(xlsx, site_to_yaml(bad, tmp_path / "b.yaml"), RULEBOOK_TEST, AleConfig())


# ------------------------------------------------------------------------------------ M203
def test_M203_solid_edges_are_not_facade() -> None:
    plain = ModulePolygon(exterior=((0, 0), (100, 0), (100, 80), (0, 80)))
    solid = ModulePolygon(
        exterior=plain.exterior, solids=(((40, 30), (40, 50), (60, 50), (60, 30)),)
    )
    along = ModuleRect(x=60, y=30, w=10, h=20)  # beside the solid, nowhere near the outline
    assert exterior_contacts(along, solid) == [] == exterior_contacts(along, plain)
    assert facade_depth(along, solid) is None
    assert solid_contact(along, solid.solids[0]) == 20
    # a courtyard, by contrast, is exterior
    court = ModulePolygon(
        exterior=plain.exterior, holes=(((40, 30), (40, 50), (60, 50), (60, 30)),)
    )
    assert exterior_contacts(along, court) == [(20, (-1, 0))]
    # a room on the outline AND along the solid: only the outline counts; depth is unchanged
    both = ModuleRect(x=40, y=50, w=20, h=30)  # top of the solid up to the top outline
    assert exterior_contacts(both, solid) == exterior_contacts(both, plain) == [(20, (0, 1))]
    assert facade_depth(both, solid) == facade_depth(both, plain) == (30, False)
    # a room away from the solid is unaffected
    away = ModuleRect(x=0, y=0, w=30, h=20)
    assert exterior_contacts(away, solid) == exterior_contacts(away, plain)
    assert solid_contact(away, solid.solids[0]) == 0


# --------------------------------------------------------------------- M204 / M208 (generation)
def _central_core_case(tmp_path: Path) -> tuple[PreparedInput, Layout]:
    from ale.optimize.anneal import anneal
    from ale.topology import seed_plan

    ring = ((0.0, 0.0), (28.8, 0.0), (28.8, 19.2), (0.0, 19.2))
    site = site_with((core("NOYAU", 12.6, 7.8, 3.0, 3.0),), ring)
    xlsx = program_to_xlsx(load_program("program_25"), tmp_path / "p.xlsx")
    cfg = AleConfig()
    cfg = cfg.model_copy(
        update={
            "optimizer": cfg.optimizer.model_copy(update={"max_iter": 400, "time_budget_s": 60.0})
        }
    )
    prepared = prepare_input(xlsx, site_to_yaml(site, tmp_path / "s.yaml"), RULEBOOK_TEST, cfg)
    rb, _ = load_rulebook(RULEBOOK_TEST)
    assert rb is not None
    seeded = seed_plan(prepared, rb, cfg, seed=1, time_budget_s=20.0)
    assert seeded.realization.layout is not None, seeded.realization.failures
    return prepared, anneal(prepared, rb, cfg, seeded.plan, seed=1).layout


@pytest.fixture(scope="module")
def central(tmp_path_factory: pytest.TempPathFactory) -> tuple[PreparedInput, Layout]:
    return _central_core_case(tmp_path_factory.mktemp("m2_central"))


def test_M204_p25_around_a_central_core(central: tuple[PreparedInput, Layout]) -> None:
    prepared, layout = central
    assert check_layout(layout, prepared, AleConfig()) == ()
    poly = layout.footprint
    (ring,) = poly.solids
    # tiles the footprint minus the solid exactly, and no room is over the core
    cells = sum(p.rect.area_cells() for p in (*layout.rooms, *layout.circulation))
    assert cells == poly.area_cells() == 288 * 192 - 30 * 30
    for p in (*layout.rooms, *layout.circulation):
        inter = ModuleRect(x=126, y=78, w=30, h=30).intersection_cells(p.rect)
        assert inter == 0, p.instance_id
    # circulation touches the core, and no SOLID_NO_ACCESS is reported
    assert any(solid_contact(c.rect, ring) >= 1 for c in layout.circulation)
    assert all(v.code != "SOLID_NO_ACCESS" for v in layout.metrics.violations)
    assert layout.fixed == ()


# ------------------------------------------------------------------------------------ M205
def _enclosed(touch: bool) -> tuple[Layout, PreparedInput]:
    """Two rooms and a corridor tiling 100 x 80 modules minus a 20 x 20 solid. With ``touch``
    the corridor passes along the solid, else rooms enclose it."""
    site = SiteSpec(
        footprint=Polygon(exterior=((0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0))),
        north_angle_deg=0.0,
        access_edge=0,
        cores=(core("C1", 3.0, 3.0, 2.0, 2.0),),
    )
    prog = Program(rooms=tuple(room(i, 30.0) for i in "ABCD"))
    prepared = prepared_from(prog, site, load_test_rulebook())
    poly = prepared.footprint.polygon
    assert poly.solids == (((30, 30), (30, 50), (50, 50), (50, 30)),)

    def pr(iid: str, spec: str | None, x: int, y: int, w: int, h: int) -> PlacedRoom:
        return PlacedRoom(
            instance_id=iid,
            spec_id=spec,
            rect=ModuleRect(x=x, y=y, w=w, h=h),
            target_area_m2=None if spec is None else 30.0,
        )

    if touch:  # corridor 10 modules wide along the left side of the solid
        circ = (pr("circ_1", None, 20, 0, 10, 80),)
        rooms = (
            pr("A", "A", 0, 0, 20, 80),
            pr("B", "B", 30, 0, 20, 30),
            pr("C", "C", 30, 50, 20, 30),
            pr("D", "D", 50, 0, 50, 80),
        )
    else:  # corridor at the top; four rooms surround the solid
        circ = (pr("circ_1", None, 0, 70, 100, 10),)
        rooms = (
            pr("A", "A", 0, 0, 30, 70),
            pr("B", "B", 30, 0, 20, 30),
            pr("C", "C", 30, 50, 20, 20),
            pr("D", "D", 50, 0, 50, 70),
        )
    base = Layout(
        grid=GridSpec(module_mm=100),
        footprint=poly,
        rooms=rooms,
        circulation=circ,
        seed=0,
        rulebook_version="t",
        metrics=evaluate_stub(),
    )
    return base.model_copy(
        update={"metrics": evaluate(base, prepared, load_test_rulebook(), AleConfig())}
    ), prepared


def evaluate_stub() -> Any:
    from ale.contracts.models import LayoutMetrics

    return LayoutMetrics(
        total_cost=0.0,
        cost_breakdown={},
        total_overshoot_m2=0.0,
        circulation_area_m2=0.0,
        residue_area_m2=0.0,
        violations=(),
    )


def test_M205_solid_enclosed_by_rooms_is_a_hard_violation() -> None:
    from ale.geometry.evaluate import hard_codes_of
    from ale.optimize.anneal import HARD_CODES, hard_count
    from ale.topology.seed import HARD_CODES as SEED_HARD

    layout, prepared = _enclosed(touch=False)
    codes = [v for v in layout.metrics.violations if v.code == "SOLID_NO_ACCESS"]
    assert len(codes) == 1
    assert "Noyau 0" in codes[0].detail and "circulation" in codes[0].detail
    assert codes[0].instance_ids == ("A", "B", "C", "D")
    # hard for the seeder and the annealer (their literal code sets are unchanged)
    assert "SOLID_NO_ACCESS" in hard_codes_of(layout.metrics, HARD_CODES)
    assert "SOLID_NO_ACCESS" in hard_codes_of(layout.metrics, SEED_HARD)
    assert hard_count(layout) >= 1
    # the invariant checker names it too when the violation was not flagged
    unflagged = layout.model_copy(
        update={
            "metrics": layout.metrics.model_copy(
                update={
                    "violations": tuple(
                        v for v in layout.metrics.violations if v.code != "SOLID_NO_ACCESS"
                    )
                }
            )
        }
    )
    assert any("solid 0" in m for m in check_layout(unflagged, prepared, AleConfig()))
    ok, _ = _enclosed(touch=True)
    assert all(v.code != "SOLID_NO_ACCESS" for v in ok.metrics.violations)


# ------------------------------------------------------------------------------------ M206
#: SHA-256 of canonical JSON, computed with the code of the base commit 62cade3 (no cores):
#: prepared inputs (feasibility reports included), seeded layouts (seed 7) and annealed layouts
#: (seed 7, 400 iterations).
BASE_DIGESTS = {
    "program_08/prepared": "0f0cdde61596562831ea3bcd675540c1615b0db9be843de687ec614990db8bb9",
    "program_08/seed": "a726a6af4a9bed790f0c9f07e876ff88eb69e359a396def897e515a5f1146842",
    "program_08/anneal": "37e372ab7519dc4a88a28ee1b93f8d174273361048e835690a1ab7d1a87cc496",
    "program_25/prepared": "22a3a34b61f5f98fe87401d4e863f89ca1d787227d2508c5390bb85de6cb56bf",
    "program_25/seed": "81f5f54cbb3a58422cd9f078578e015d8e64b4e21f0786cd4e8654899d6bcae6",
    "program_25/anneal": "2abd1235854a289f6e300f6b069cfbc54e2db112b8b41a5bbf4f1cd205970380",
    "program_60/prepared": "2e2dada9ad9056f08b89671eff2669b51c6a868d37199d5de61e3b4c627d415b",
    "program_60/seed": "c4f6f1fed33968ca6bb778e98cc0b0070573235c6d3d26b690eae1b70a6d9e72",
}


def _digest(model: Any) -> str:
    return hashlib.sha256(canonical_json(model)).hexdigest()


def test_M206_sites_without_cores_are_byte_identical(tmp_path: Path) -> None:
    from ale.optimize.anneal import anneal
    from ale.topology import seed_plan

    rbp = write_rulebook(load_test_rulebook(), tmp_path / "rb.yaml")
    cfg = AleConfig()
    cfg = cfg.model_copy(
        update={
            "optimizer": cfg.optimizer.model_copy(update={"max_iter": 400, "time_budget_s": 600.0})
        }
    )
    rb, _ = load_rulebook(rbp)
    assert rb is not None
    got: dict[str, str] = {}
    for prog, site in FIXTURE_PAIRS:
        xlsx = program_to_xlsx(load_program(prog), tmp_path / f"{prog}.xlsx")
        prepared = prepare_input(xlsx, DATA_DIR / f"{site}.yaml", rbp, cfg)
        got[f"{prog}/prepared"] = _digest(prepared)
        seeded = seed_plan(prepared, rb, cfg, seed=7, time_budget_s=600.0)
        assert seeded.realization.layout is not None
        got[f"{prog}/seed"] = _digest(seeded.realization.layout)
        if prog != "program_60":  # the P60 annealing alone takes ~6 s
            got[f"{prog}/anneal"] = _digest(anneal(prepared, rb, cfg, seeded.plan, seed=7).layout)
    assert got == {k: v for k, v in BASE_DIGESTS.items() if k in got}
    assert len(got) == 8


# ------------------------------------------------------------------------------------ M208
def _with_fixed(layout: Layout) -> Layout:
    r = ModuleRect(x=126, y=78, w=30, h=30)
    fixed = (
        PlacedRoom(
            instance_id="NOYAU",
            spec_id=None,
            rect=ModuleRect(x=r.x, y=r.y, w=15, h=30),
            target_area_m2=None,
        ),
        PlacedRoom(
            instance_id="WC_1",
            spec_id="WC",
            rect=ModuleRect(x=r.x + 15, y=r.y, w=15, h=30),
            target_area_m2=4.5,
        ),
    )
    return Layout.model_validate({**layout.model_dump(), "fixed": [p.model_dump() for p in fixed]})


def test_M208_exports_draw_solids_and_fixed_rooms(
    central: tuple[PreparedInput, Layout], tmp_path: Path
) -> None:
    import ezdxf

    from ale.export import export_run

    prepared, base = central
    layout = _with_fixed(base)
    files = export_run(layout, prepared, tmp_path / "out", rulebook_version="t", run_id="m2")
    # JSON round-trips, fixed rooms included
    assert files.layout_json is not None
    back = Layout.model_validate_json(files.layout_json.read_bytes())
    assert back.fixed == layout.fixed and back.footprint == layout.footprint
    assert [p.instance_id for p in back.fixed] == ["NOYAU", "WC_1"]
    assert canonical_json(back) == files.layout_json.read_bytes()
    # DXF: solid + fixed layers, the hatch and the core id label
    assert files.layout_dxf is not None
    doc = ezdxf.readfile(files.layout_dxf)
    assert {"ALE_SOLID", "ALE_FIXED"} <= {la.dxf.name for la in doc.layers}
    msp = doc.modelspace()
    assert len(msp.query('HATCH[layer=="ALE_SOLID"]')) == 1
    assert len(msp.query('LWPOLYLINE[layer=="ALE_SOLID"]')) == 1
    assert len(msp.query('LWPOLYLINE[layer=="ALE_FIXED"]')) == 2
    texts = [t.text for t in msp.query('MTEXT[layer=="ALE_SOLID"]')]
    assert texts == ["NOYAU"]
    # SVG: hatched solid labelled with the core id, fixed rooms
    svg = files.preview_svg.read_text(encoding="utf-8")
    assert 'id="solids"' in svg and 'class="solid"' in svg and ">NOYAU</text>" in svg
    assert svg.count('class="fixed"') == 2
    import xml.dom.minidom

    xml.dom.minidom.parseString(svg)


def test_M208_no_solid_no_extra_layer(tmp_path: Path) -> None:
    import ezdxf

    from ale.export import export_run

    prepared = prepared_from(
        Program(rooms=(room("R1", 30.0),)),
        SiteSpec(
            footprint=Polygon(exterior=((0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0))),
            north_angle_deg=0.0,
            access_edge=0,
        ),
        load_test_rulebook(),
    )
    layout = Layout(
        grid=GridSpec(module_mm=100),
        footprint=prepared.footprint.polygon,
        rooms=(
            PlacedRoom(
                instance_id="R1",
                spec_id="R1",
                rect=ModuleRect(x=0, y=0, w=60, h=50),
                target_area_m2=30.0,
            ),
        ),
        circulation=(),
        seed=0,
        rulebook_version="t",
        metrics=evaluate_stub(),
    )
    files = export_run(layout, prepared, tmp_path / "o", rulebook_version="t", run_id="x")
    assert files.layout_dxf is not None
    names = {la.dxf.name for la in ezdxf.readfile(files.layout_dxf).layers}
    assert not {"ALE_SOLID", "ALE_FIXED"} & names
    assert 'id="solids"' not in files.preview_svg.read_text(encoding="utf-8")


def test_M208_invalid_solid_in_layout_rejected() -> None:
    with pytest.raises(ValidationError):
        ModulePolygon(
            exterior=((0, 0), (10, 0), (10, 10), (0, 10)),
            solids=(((0, 2), (0, 4), (3, 4), (3, 2)),),
        )
