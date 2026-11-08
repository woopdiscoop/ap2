"""D01 layer proposal, D02 units (Ticket 1.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cad_helpers import add_block, add_plan_pairs, new_doc, read, save

from ale.cad import LayerMap, LayerRole, load_layer_map, propose_layer_map, save_layer_map
from ale.cad.layers import canon_layer, propose_role
from ale.cad.units import UNITS_INFERRED_WARNING, infer_from_door_widths, resolve_units
from ale.contracts.enums import ScaleMethod

R = LayerRole

#: 20 layer names → expected role (literal reading of RD 1.2 §3: first group wins).
LAYER_TABLE: dict[str, LayerRole] = {
    "MUR": R.WALL,
    "A-WALL": R.WALL,
    "Cloisons": R.WALL,
    "PORTES": R.DOOR,
    "A-DOOR": R.DOOR,
    "Menuiseries ext": R.WINDOW,
    "TEXTE LOCAUX": R.ZONE,  # LOCAUX (zone group) precedes TEXTE (room-label group)
    "Surfaces": R.AREA_LABEL,
    "ZONES": R.ZONE,
    "COTATIONS": R.IGNORE,  # no keyword ("COTE" is not a substring of "COTATIONS")
    "Mobilier": R.FURNITURE,
    "0": R.IGNORE,
    "Defpoints": R.IGNORE,
    "FENÊTRES": R.WINDOW,
    "A-ANNO-TEXT": R.ROOM_LABEL,
    "HACHURES": R.IGNORE,
    "HACH ZONE": R.ZONE,
    "Voiles béton": R.WALL,
    "A-AREA-IDEN": R.ZONE,
    "COTES": R.IGNORE,
}


def test_D01_layer_proposal() -> None:
    assert len(LAYER_TABLE) == 20
    proposed = propose_layer_map(LAYER_TABLE)
    assert proposed.layers == LAYER_TABLE
    existing = LayerMap.model_validate({"layers": {"0": "WALL"}})
    merged = propose_layer_map(LAYER_TABLE, existing=existing)
    assert merged.layers["0"] is R.WALL
    assert merged.layers["MUR"] is R.WALL
    assert merged.layers["COTATIONS"] is R.IGNORE


def test_D01_layer_proposal_details(tmp_path: Path) -> None:
    assert canon_layer("Fenêtre-Ext.") == "FENETREEXT"
    assert propose_role("whatever") is R.IGNORE
    assert propose_role("SURFACE M2") is R.AREA_LABEL
    lm = propose_layer_map(["MUR", "PORTES", "Libellés"])
    path = tmp_path / "layer_map é.yaml"
    save_layer_map(lm, path)
    text = path.read_text(encoding="utf-8")
    assert "MUR: wall" in text and text.startswith("# Map CAD layer names")
    assert load_layer_map(path) == lm
    assert lm.role("unknown layer") is R.IGNORE
    template = Path(__file__).resolve().parents[2] / "src" / "ale" / "templates" / "layer_map.yaml"
    assert load_layer_map(template).layers == {}
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_layer_map(empty).layers == {}


@pytest.mark.parametrize(
    ("code", "expected", "label"),
    [(4, 0.001, "mm"), (5, 0.01, "cm"), (6, 1.0, "m"), (1, 0.0254, "in")],
)
def test_D02_units(tmp_path: Path, code: int, expected: float, label: str) -> None:
    doc = new_doc(insunits=code)
    add_plan_pairs(doc.modelspace(), scale=0.001 / expected)
    res = read(save(doc, tmp_path / f"u{code}.dxf"))
    assert res.plans, res.warnings
    plan = res.plans[0]
    assert plan.scale_m_per_unit == pytest.approx(expected)
    assert plan.units_label == label
    assert plan.scale_method is ScaleMethod.DRAWING_UNITS
    assert plan.scale_confidence == 1.0


def test_D02_units_inferred_from_doors(tmp_path: Path) -> None:
    doc = new_doc(insunits=None)
    add_plan_pairs(doc.modelspace(), door_gap=(1000, 1900))
    add_block(doc, "DOOR", 900, 50)
    doc.modelspace().add_blockref(
        "DOOR", (4075, 1000), dxfattribs={"layer": "PORTES", "rotation": 90}
    )
    res = read(save(doc, tmp_path / "doors.dxf"))
    plan = res.plans[0]
    assert plan.scale_m_per_unit == pytest.approx(0.001)
    assert plan.scale_confidence == pytest.approx(0.6)
    assert UNITS_INFERRED_WARNING in res.warnings
    assert UNITS_INFERRED_WARNING in plan.warnings


def test_D02_units_override(tmp_path: Path) -> None:
    doc = new_doc(insunits=0)
    add_plan_pairs(doc.modelspace(), scale=0.1)  # centimetres
    path = save(doc, tmp_path / "cm.dxf")
    res = read(path, units_override="cm")
    assert res.plans[0].scale_m_per_unit == pytest.approx(0.01)
    assert res.plans[0].units_label == "cm"
    unknown = read(path)
    assert unknown.plans == () or unknown.plans[0].scale_method is ScaleMethod.UNKNOWN
    assert any("units unknown" in w for w in unknown.warnings)


def test_D02_units_rules() -> None:
    assert infer_from_door_widths([90.0, 80.0, 100.0]) == "cm"
    assert infer_from_door_widths([0.9]) == "m"
    assert infer_from_door_widths([5000.0]) is None
    assert infer_from_door_widths([]) is None
    ft = resolve_units(2, [], None)
    assert ft.m_per_unit == pytest.approx(0.3048)
    bad = resolve_units(None, [], "furlong")
    assert bad.method is ScaleMethod.UNKNOWN and bad.m_per_unit is None
    assert any("furlong" in w for w in bad.warnings)
    # $INSUNITS wins over doors and override
    assert resolve_units(6, [900.0], "mm").label == "m"
