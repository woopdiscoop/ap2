"""Write ``programme_template.xlsx`` (French headers, drop-down lists from the taxonomy).

Usage: ``python -m ale.program.template OUT.xlsx``. The committed copy lives in
``ale/templates/programme_template.xlsx`` and is regenerated content-equal by this script.
Areas are m², widths metres.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ale.contracts.enums import MacroZone, TypeCategory
from ale.contracts.models import Program, RoomSpec
from ale.contracts.taxonomy import load_taxonomy
from ale.program.excel import (
    ANCHOR_LABELS,
    COL_ANCHOR,
    COL_AREA,
    COL_FACADE,
    COL_QTY,
    COL_TYPE,
    COL_ZONE,
    HEADERS,
    ORIENTATION_COLUMNS,
    SHEET_NAME,
    ZONE_LABELS,
)

__all__ = [
    "EXAMPLE_PROGRAM",
    "EXAMPLE_SHEET",
    "HELP_SHEET",
    "LISTS_SHEET",
    "TEMPLATE_PATH",
    "VALIDATION_LAST_ROW",
    "main",
    "program_rows",
    "type_labels",
    "write_template",
]

EXAMPLE_SHEET = "Exemple"
HELP_SHEET = "Aide"
LISTS_SHEET = "Listes"
VALIDATION_LAST_ROW = 500
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "programme_template.xlsx"

_FIXED_TIME = _dt.datetime(2026, 1, 1, 0, 0, 0)

_A = MacroZone.ADMINISTRATIVE
_P = MacroZone.PUBLIC
_S = MacroZone.SERVICES

#: Fixture P8 (``program_08.yaml``): the rows of the ``Exemple`` sheet.
EXAMPLE_PROGRAM = Program(
    rooms=(
        RoomSpec(
            id="R01",
            name="Hall d'entrée",
            type="entrance_hall",
            target_area_m2=12.0,
            macro_zone=_P,
            needs_facade=True,
            adjacent_to=("R02",),
        ),
        RoomSpec(id="R02", name="Accueil", type="reception", target_area_m2=9.0, macro_zone=_P),
        RoomSpec(
            id="R03",
            name="Bureau",
            type="office",
            target_area_m2=12.0,
            quantity=2,
            macro_zone=_A,
            needs_facade=True,
        ),
        RoomSpec(
            id="R04",
            name="Salle de réunion",
            type="meeting_room",
            target_area_m2=16.0,
            macro_zone=_A,
            needs_facade=True,
            avoid=("R05",),
        ),
        RoomSpec(id="R05", name="Sanitaires", type="sanitary", target_area_m2=6.0, macro_zone=_S),
        RoomSpec(id="R06", name="Rangement", type="storage", target_area_m2=4.0, macro_zone=_S),
        RoomSpec(
            id="R07",
            name="Local technique",
            type="technical_room",
            target_area_m2=4.0,
            macro_zone=_S,
            min_width_m=1.5,
        ),
    )
)

#: ``Aide`` sheet: (header, required?, accepted values) per column, RD 3.1 section 4.
_HELP_ROWS: tuple[tuple[str, str, str], ...] = (
    ("ID", "Oui", "Identifiant unique : 1 à 32 caractères parmi A-Z, a-z, 0-9, _ et -."),
    ("Nom", "Oui", "Texte non vide (120 caractères au plus)."),
    (
        "Type",
        "Oui",
        "Type de pièce : libellé de la liste, clé de la taxonomie ou synonyme exact "
        "(pièces et circulations verticales uniquement).",
    ),
    (
        "Surface (m²)",
        "Oui",
        "Nombre > 0 et ≤ 10 000 ; la virgule décimale est acceptée (12,5).",
    ),
    ("Quantité", "Non (1)", "Entier de 1 à 500."),
    (
        "Zone",
        "Non",
        "Public, Administratif ou Services ; vide = zone par défaut du type.",
    ),
    ("Façade", "Non (Non)", "Oui/Non, O/N, X/vide, 1/0, Vrai/Faux."),
    ("Orientation N", "Non", "Nombre entre -1 et 1 ; si une orientation est remplie, vide = 0."),
    ("Orientation E", "Non", "Nombre entre -1 et 1 ; si une orientation est remplie, vide = 0."),
    ("Orientation S", "Non", "Nombre entre -1 et 1 ; si une orientation est remplie, vide = 0."),
    (
        "Orientation O",
        "Non",
        "Nombre entre -1 et 1 (O = Ouest) ; si une orientation est remplie, vide = 0.",
    ),
    ("Largeur min (m)", "Non", "Nombre > 0, en mètres."),
    ("Adjacent à", "Non", "Identifiants de pièces séparés par , ou ;."),
    ("Éviter", "Non", "Identifiants de pièces séparés par , ou ;."),
    (
        "Niveau",
        "Non (0)",
        "Entier ≥ 0 (les moteurs v1 n'acceptent qu'un seul niveau par programme).",
    ),
    ("Ancrage", "Non", "Coin ou Entrée (liste) ; vide = aucun ancrage."),
    ("Remarques", "Non", "Texte libre, ignoré."),
)

_WIDTHS: dict[str, float] = {
    "ID": 10,
    "Nom": 28,
    "Type": 30,
    "Surface (m²)": 13,
    "Quantité": 10,
    "Zone": 15,
    "Façade": 9,
    "Largeur min (m)": 15,
    "Adjacent à": 18,
    "Éviter": 18,
    "Niveau": 8,
    "Ancrage": 12,
    "Remarques": 30,
}


def type_labels() -> tuple[str, ...]:
    """``label_fr`` of every ROOM / VERTICAL taxonomy type, in taxonomy order."""
    return tuple(
        t.label_fr
        for t in load_taxonomy().types
        if t.category in (TypeCategory.ROOM, TypeCategory.VERTICAL)
    )


def _fmt_number(x: float) -> float | int:
    return int(x) if float(x).is_integer() else x


def program_rows(program: Program) -> list[list[Any]]:
    """Rows (17 cells, template column order) of a program: types as ``label_fr``."""
    tax = load_taxonomy()
    rows: list[list[Any]] = []
    for r in program.rooms:
        orient = r.orientation_override
        rows.append(
            [
                r.id,
                r.name,
                tax.get(r.type).label_fr,
                _fmt_number(r.target_area_m2),
                r.quantity,
                ZONE_LABELS[r.macro_zone],
                "Oui" if r.needs_facade else "Non",
                *(None if orient is None else orient.get(b, 0.0) for _, b in ORIENTATION_COLUMNS),
                r.min_width_m,
                ", ".join(r.adjacent_to) or None,
                ", ".join(r.avoid) or None,
                r.floor,
                None if r.anchor is None else ANCHOR_LABELS[r.anchor],
                None,
            ]
        )
    return rows


def _column_letter(header: str) -> str:
    from openpyxl.utils import get_column_letter  # type: ignore[import-untyped,unused-ignore]

    return str(get_column_letter(HEADERS.index(header) + 1))


def _header_sheet(ws: Any) -> None:
    from openpyxl.styles import Font  # type: ignore[import-untyped,unused-ignore]

    ws.append(list(HEADERS))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for header in HEADERS:
        ws.column_dimensions[_column_letter(header)].width = _WIDTHS.get(header, 14)


def _validations(ws: Any, n_types: int) -> None:
    from openpyxl.worksheet.datavalidation import (  # type: ignore[import-untyped,unused-ignore]
        DataValidation,
    )

    def add(header: str, dv: Any, title: str, message: str) -> None:
        col = _column_letter(header)
        dv.errorTitle = title
        dv.error = message
        dv.showErrorMessage = True
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{VALIDATION_LAST_ROW}")

    zones = ",".join(ZONE_LABELS[z] for z in MacroZone)
    add(
        COL_TYPE,
        DataValidation(type="list", formula1=f"{LISTS_SHEET}!$A$1:$A${n_types}", allow_blank=True),
        "Type",
        "Choisissez un type dans la liste.",
    )
    add(
        COL_ZONE,
        DataValidation(type="list", formula1=f'"{zones}"', allow_blank=True),
        "Zone",
        "Public, Administratif ou Services.",
    )
    add(
        COL_FACADE,
        DataValidation(type="list", formula1='"Oui,Non"', allow_blank=True),
        "Façade",
        "Oui ou Non.",
    )
    add(
        COL_ANCHOR,
        DataValidation(
            type="list",
            formula1='"' + ",".join(ANCHOR_LABELS.values()) + '"',
            allow_blank=True,
        ),
        "Ancrage",
        "Coin ou Entrée.",
    )
    add(
        COL_AREA,
        DataValidation(type="decimal", operator="greaterThan", formula1="0", allow_blank=True),
        "Surface",
        "La surface doit être un nombre > 0 (m²).",
    )
    add(
        COL_QTY,
        DataValidation(type="whole", operator="greaterThanOrEqual", formula1="1", allow_blank=True),
        "Quantité",
        "La quantité doit être un entier ≥ 1.",
    )


def write_template(out: Path) -> Path:
    """Write the program template to ``out`` (overwrites) and return the path."""
    import openpyxl  # type: ignore[import-untyped,unused-ignore]
    from openpyxl.styles import Font  # type: ignore[import-untyped,unused-ignore]

    labels = type_labels()
    wb = openpyxl.Workbook()
    wb.properties.creator = "ALE"
    wb.properties.created = _FIXED_TIME
    wb.properties.modified = _FIXED_TIME

    ws = wb.active
    ws.title = SHEET_NAME
    _header_sheet(ws)
    _validations(ws, len(labels))

    ex = wb.create_sheet(EXAMPLE_SHEET)
    _header_sheet(ex)
    for row in program_rows(EXAMPLE_PROGRAM):
        ex.append(row)

    aide = wb.create_sheet(HELP_SHEET)
    aide.append(["Colonne", "Obligatoire", "Valeurs acceptées"])
    for cell in aide[1]:
        cell.font = Font(bold=True)
    for help_row in _HELP_ROWS:
        aide.append(list(help_row))
    aide.freeze_panes = "A2"
    for letter, width in (("A", 18), ("B", 14), ("C", 90)):
        aide.column_dimensions[letter].width = width

    lists = wb.create_sheet(LISTS_SHEET)
    for label in labels:
        lists.append([label])
    lists.sheet_state = "hidden"

    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb.save(target)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point: ``python -m ale.program.template OUT.xlsx``."""
    parser = argparse.ArgumentParser(prog="python -m ale.program.template")
    parser.add_argument("out", type=Path, help="output .xlsx file (overwritten)")
    args = parser.parse_args(argv)
    path = write_template(args.out)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
