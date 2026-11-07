"""Test utilities of Ticket 3.1: workbooks, site files and rulebooks written on the fly."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from ale.contracts.enums import Bearing, MacroZone
from ale.contracts.models import Program, Rulebook, SiteSpec
from ale.contracts.serialization import dump_yaml, load_yaml
from ale.contracts.taxonomy import load_taxonomy

DATA = Path(__file__).resolve().parent / "data"
RULEBOOK_TEST = DATA / "rulebook_test.yaml"

#: The 16 headers of RD 3.1 section 4, in order (written here independently of the code).
HEADERS = [
    "ID",
    "Nom",
    "Type",
    "Surface (m²)",
    "Quantité",
    "Zone",
    "Façade",
    "Orientation N",
    "Orientation E",
    "Orientation S",
    "Orientation O",
    "Largeur min (m)",
    "Adjacent à",
    "Éviter",
    "Niveau",
    "Remarques",
]
ZONES_FR = {
    MacroZone.PUBLIC: "Public",
    MacroZone.ADMINISTRATIVE: "Administratif",
    MacroZone.SERVICES: "Services",
}


def write_rows(
    path: Path,
    rows: Sequence[Sequence[Any]],
    headers: Sequence[Any] = HEADERS,
    sheet: str = "Programme",
) -> Path:
    """Write ``headers`` + ``rows`` into one sheet of a new workbook."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


def row(**cells: Any) -> list[Any]:
    """A row in the 16 columns from keyword cells (``ID``, ``Nom``, ``Surface``, ...).

    Keys are header names with spaces/accents replaced: ``Surface``, ``Quantite``,
    ``Facade``, ``N``/``E``/``S``/``O``, ``Largeur``, ``Adjacent``, ``Eviter``, ``Niveau``.
    """
    keys = [
        "ID",
        "Nom",
        "Type",
        "Surface",
        "Quantite",
        "Zone",
        "Facade",
        "N",
        "E",
        "S",
        "O",
        "Largeur",
        "Adjacent",
        "Eviter",
        "Niveau",
        "Remarques",
    ]
    unknown = set(cells) - set(keys)
    assert not unknown, unknown
    return [cells.get(k) for k in keys]


def good_row(rid: Any = "R01", **over: Any) -> list[Any]:
    """A valid office row (12 m², Administratif), with overrides."""
    base: dict[str, Any] = {
        "ID": rid,
        "Nom": "Bureau",
        "Type": "Bureau",
        "Surface": 12,
        "Zone": "Administratif",
    }
    base.update(over)
    return row(**base)


#: The X07 workbook: rows 2-13, one error code each.
X07_ROWS: list[tuple[str, list[Any]]] = [
    ("E_EMPTY_ID", good_row(None)),
    ("E_BAD_ID", good_row("R 1")),
    ("E_EMPTY_NAME", good_row("R04", Nom=None)),
    ("E_DUP_ID", good_row("R04")),
    ("E_UNKNOWN_TYPE", good_row("R06", Type="Truc inconnu")),
    ("E_FORBIDDEN_TYPE", good_row("R07", Type="Circulation")),
    ("E_AREA", good_row("R08", Surface="abc")),
    ("E_QUANTITY", good_row("R09", Quantite=3.5)),
    ("E_ZONE", good_row("R10", Zone="Bureaux")),
    ("E_FACADE", good_row("R11", Facade="peut-être")),
    ("E_MIN_WIDTH", good_row("R12", Largeur=-1)),
    ("E_FLOOR", good_row("R13", Niveau=1)),
]


def write_x07(path: Path) -> Path:
    return write_rows(path, [r for _, r in X07_ROWS])


def program_to_xlsx(program: Program, path: Path) -> Path:
    """Write a ``Program`` into the RD section 4 columns (types as ``label_fr``)."""
    tax = load_taxonomy()
    rows = []
    for r in program.rooms:
        o = r.orientation_override
        rows.append(
            [
                r.id,
                r.name,
                tax.get(r.type).label_fr,
                r.target_area_m2,
                r.quantity,
                ZONES_FR[r.macro_zone],
                "Oui" if r.needs_facade else "Non",
                *(None if o is None else o.get(b, 0.0) for b in Bearing),
                r.min_width_m,
                "; ".join(r.adjacent_to) or None,
                "; ".join(r.avoid) or None,
                r.floor,
                None,
            ]
        )
    return write_rows(path, rows)


def write_site_yaml(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def site_to_yaml(site: SiteSpec, path: Path) -> Path:
    """Write a ``SiteSpec`` as ``site.yaml`` with an inline ``footprint``."""
    data: dict[str, Any] = {
        "footprint": [list(p) for p in site.footprint.exterior],
        "north_angle_deg": site.north_angle_deg,
        "access_edge": site.access_edge,
        "core_hint": None if site.core_hint is None else list(site.core_hint),
    }
    return write_site_yaml(path, data)


def write_dxf(
    path: Path,
    polylines: Sequence[Sequence[tuple[float, float]]],
    insunits: int | None = 4,
    layer: str = "EMPRISE",
    closed: bool = True,
) -> Path:
    """Write closed LWPOLYLINEs on ``layer`` with ``$INSUNITS``."""
    import ezdxf

    doc = ezdxf.new("R2010")
    if insunits is not None:
        doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    for pts in polylines:
        msp.add_lwpolyline(list(pts), close=closed, dxfattribs={"layer": layer})
    doc.saveas(path)
    return path


def load_test_rulebook() -> Rulebook:
    return load_yaml(Rulebook, RULEBOOK_TEST.read_text(encoding="utf-8"))


def write_rulebook(rulebook: Rulebook, path: Path) -> Path:
    path.write_text(dump_yaml(rulebook), encoding="utf-8")
    return path
