"""Test M201 (Ticket M.2): contracts 1.7.0 — ``ModulePolygon.solids`` and ``Layout.fixed``.

Empty ``solids`` / ``fixed`` leave the serialised form unchanged (byte-identical outputs for
sites without cores); the validation of solids follows the one of courtyard holes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from ale.contracts import export_schemas, lock
from ale.contracts.geometry import ModulePolygon, ModuleRect, to_shapely
from ale.contracts.models import GridSpec, Layout, LayoutMetrics, PlacedRoom
from ale.contracts.serialization import canonical_json
from ale.contracts.version import CONTRACTS_VERSION

EXT = ((0, 0), (100, 0), (100, 80), (0, 80))
SOLID = ((30, 30), (30, 50), (50, 50), (50, 30))  # clockwise


def poly(**kw: Any) -> ModulePolygon:
    return ModulePolygon(exterior=EXT, **kw)


def test_M201_version_lock_and_schemas() -> None:
    assert CONTRACTS_VERSION == "1.7.0"
    assert lock.main(["--check"]) == 0
    assert export_schemas.main(["--check"]) == 0
    layout_schema = json.loads(
        (export_schemas.SCHEMA_DIR / "Layout.schema.json").read_text("utf-8")
    )
    assert "fixed" in layout_schema["properties"]
    assert "solids" in layout_schema["$defs"]["ModulePolygon"]["properties"]


def test_M201_solid_accepted_and_excluded_from_area() -> None:
    p = poly(solids=(SOLID,))
    assert p.area_cells() == 100 * 80 - 20 * 20
    with_hole = poly(
        holes=(((70, 20), (70, 40), (90, 40), (90, 20)),),
        solids=(SOLID,),
    )
    assert with_hole.area_cells() == 100 * 80 - 400 - 400
    assert to_shapely(p).area == p.area_cells()


def test_M201_empty_solids_serialise_as_before() -> None:
    plain = poly()
    assert "solids" not in plain.model_dump()
    assert "solids" not in json.loads(plain.model_dump_json())
    assert "holes" not in plain.model_dump()
    dumped = poly(solids=(SOLID,)).model_dump()
    assert dumped["solids"] == (SOLID,)
    assert ModulePolygon.model_validate(dumped) == poly(solids=(SOLID,))


@pytest.mark.parametrize(
    ("ring", "why"),
    [
        (((30, 30), (50, 30), (50, 50), (30, 50)), "clockwise"),  # counter-clockwise
        (((30, 30), (30, 50), (50, 60), (50, 30)), "axis-parallel"),
        (((30, 30), (30, 40), (30, 50), (50, 50), (50, 30)), "collinear"),
        (((30, 30), (30, 50), (50, 50)), "4 vertices"),
        (((0, 30), (0, 50), (20, 50), (20, 30)), "strictly inside"),  # touches the exterior
        (((90, 30), (90, 50), (110, 50), (110, 30)), "strictly inside"),  # sticks out
    ],
)
def test_M201_bad_solids_rejected(ring: tuple[tuple[int, int], ...], why: str) -> None:
    with pytest.raises(ValidationError, match=why):
        poly(solids=(ring,))


def test_M201_solids_must_not_touch_holes_or_each_other() -> None:
    hole = ((60, 30), (60, 50), (80, 50), (80, 30))
    with pytest.raises(ValidationError, match="strictly inside"):
        poly(holes=(hole,), solids=(((50, 30), (50, 50), (60, 50), (60, 30)),))  # shares an edge
    other = ((50, 30), (50, 50), (70, 50), (70, 30))  # shares an edge with SOLID
    with pytest.raises(ValidationError, match="touches solid"):
        poly(solids=(SOLID, other))
    overlap = ((40, 40), (40, 60), (60, 60), (60, 40))
    with pytest.raises(ValidationError, match="solid"):
        poly(solids=(SOLID, overlap))
    far = ((60, 30), (60, 50), (80, 50), (80, 30))
    assert len(poly(solids=(SOLID, far)).solids) == 2


# ----------------------------------------------------------------------------- Layout.fixed
def placed(iid: str, x: int, y: int, w: int, h: int) -> PlacedRoom:
    return PlacedRoom(
        instance_id=iid, spec_id=None, rect=ModuleRect(x=x, y=y, w=w, h=h), target_area_m2=None
    )


def layout(fixed: tuple[PlacedRoom, ...] = (), solids: bool = True) -> Layout:
    return Layout(
        grid=GridSpec(module_mm=100),
        footprint=poly(solids=(SOLID,)) if solids else poly(),
        rooms=(),
        circulation=(),
        seed=0,
        rulebook_version="t",
        metrics=LayoutMetrics(
            total_cost=0.0,
            cost_breakdown={},
            total_overshoot_m2=0.0,
            circulation_area_m2=0.0,
            residue_area_m2=0.0,
            violations=(),
        ),
        fixed=fixed,
    )


def test_M201_fixed_rooms_valid_and_omitted_when_empty() -> None:
    assert "fixed" not in layout().model_dump()
    assert b'"fixed"' not in canonical_json(layout())
    got = layout((placed("A", 30, 30, 10, 20), placed("B", 40, 30, 10, 20)))
    dumped = got.model_dump()
    assert [p["instance_id"] for p in dumped["fixed"]] == ["A", "B"]
    assert Layout.model_validate_json(canonical_json(got)) == got


def test_M201_fixed_rooms_checked() -> None:
    with pytest.raises(ValidationError, match="inside a solid"):
        layout((placed("A", 20, 30, 20, 20),))  # sticks out of the solid
    with pytest.raises(ValidationError, match="inside a solid"):
        layout((placed("A", 30, 30, 10, 10),), solids=False)  # no solid at all
    with pytest.raises(ValidationError, match="overlap"):
        layout((placed("A", 30, 30, 15, 20), placed("B", 40, 30, 10, 20)))
    with pytest.raises(ValidationError, match="sorted"):
        layout((placed("B", 40, 30, 10, 20), placed("A", 30, 30, 10, 20)))
    with pytest.raises(ValidationError, match="duplicate"):
        layout((placed("A", 30, 30, 10, 20), placed("A", 40, 30, 10, 20)))


def test_M201_nan_metric_still_rejected() -> None:
    """The wrap serializer of ``Layout`` must not turn a NaN into ``null``."""
    bad = layout().model_copy(
        update={"metrics": layout().metrics.model_copy(update={"total_cost": float("nan")})}
    )
    with pytest.raises(ValueError):
        canonical_json(bad)
