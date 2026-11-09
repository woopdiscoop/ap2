"""Synthetic "programme physique" workbooks shaped like the AREP-MS Annexe (Ticket P.2).

The real Annexe is a competition document and is never committed: these builders only
reproduce its shape (title rows, repeated headers, merged ENTITE cells, totals, notes).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

HEADER = ["ENTITE", "ESPACE", "NOMBRE", "SURFACE UNITAIRE EN m2", "SURFACE TOTALE EN m2"]
HEADER_VARIANT = ["Entité", "espace", "Nombre", "Surface unitaire en m²", "Surface Totale (m²)"]

RULEBOOK_TEST = Path(__file__).resolve().parents[1] / "program" / "data" / "rulebook_test.yaml"

#: An entity block: (entity, [(espace, nombre, surface unitaire), ...]).
Block = tuple[str, Sequence[tuple[Any, Any, Any]]]


@dataclass
class Sheet:
    """Rows of one sheet plus the ENTITE cell ranges to merge."""

    rows: list[list[Any]] = field(default_factory=list)
    merges: list[str] = field(default_factory=list)

    def add(self, *cells: Any) -> int:
        self.rows.append(list(cells))
        return len(self.rows)

    def blocks(self, blocks: Sequence[Block], merge: bool = True) -> None:
        for entity, lines in blocks:
            first = len(self.rows) + 1
            for i, (espace, nombre, unit) in enumerate(lines):
                total = nombre * unit if isinstance(unit, int | float) else None
                self.add(entity if i == 0 else None, espace, nombre, unit, total)
            last = len(self.rows)
            if merge and last > first:
                self.merges.append(f"A{first}:A{last}")

    def save(self, path: Path, title: str = "Programme physique") -> Path:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = title
        for row in self.rows:
            ws.append(row)
        for rng in self.merges:
            ws.merge_cells(rng)
        wb.save(path)
        return path


REGION_BLOCKS: list[Block] = [
    (
        "ACCUEIL",
        [("Hall d'entrée/Accueil", 1, 60), ("Loge gardien", 1, 12), ("Bureau d'ordre", 1, 16)],
    ),
    (
        "PARKING EXTERIEUR",
        [("Parking à ciel ouvert (80 places)", 1, "Selon conception du parking")],
    ),
    ("ESPACE COMMUN", [("Sanitaires H/F", 2, 20), ("Salle de prière", 1, 30)]),
    (
        "ESPACE CONFERENCE",
        [("Salle de conférence (150 places)", 1, 180), ("Local technique / Régie", 1, 6)],
    ),
    (
        "DIRECTION DES RESSOURCES",
        [("Bureau - Chef de Service", 8, 16), ("Secrétariat/Attente", 1, 20)],
    ),
]
AREP_BLOCKS: list[Block] = [
    (
        "DIRECTION GENERALE",
        [
            ("Bureau du Directeur", 1, 30),
            ("Salle de réunion", 1, 24),
            ("Bureaux en open space", 1, 150),
        ],
    ),
    ("SERVICES GENERAUX", [("Archives", 2, 15), ("Local pour chauffeurs", 1, 12)]),
]

#: (lines, instances, useful m²) of each building of :func:`arep_like`.
REGION_COUNTS = (9, 17, 492.0)
AREP_COUNTS = (5, 6, 246.0)


def arep_like(
    path: Path,
    region_total: float = 492,
    arep_header: Sequence[str] = HEADER,
    region_blocks: Sequence[Block] = REGION_BLOCKS,
) -> Path:
    """Two buildings (second title with the ``PHYIQUE`` typo), merged ENTITE cells, totals."""
    s = Sheet()
    s.add("ROYAUME DU MAROC — CONCOURS D'ARCHITECTURE")
    s.add("ANNEXE 3")
    s.add("PROGRAMME PHYSIQUE : SIEGE DE LA REGION")
    s.add(*HEADER)
    s.blocks(region_blocks)
    s.add("TOTAL SUPERFICIE UTILE DU SIEGE EN M²", None, None, None, region_total)
    s.add("(+) Circulation 25%", None, None, None, 123)
    s.add("TOTAL GENERAL", None, None, None, 615)
    s.add("NB : les surfaces sont données à titre indicatif ; programme physique non contractuel.")
    s.add()
    s.add("PROGRAMME PHYIQUE - AREP")
    s.add(*arep_header)
    s.blocks(AREP_BLOCKS)
    s.add("TOTAL SUPERFICIE UTILE AREP EN M²", None, None, None, 246)
    return s.save(path)


def simple_annexe(path: Path, blocks: Sequence[Block], title: str = "PROGRAMME PHYSIQUE X") -> Path:
    s = Sheet()
    s.add(title)
    s.add(*HEADER)
    s.blocks(blocks)
    return s.save(path)


def write_site(path: Path, side_m: float = 60.0) -> Path:
    data = {
        "footprint": [[0.0, 0.0], [side_m, 0.0], [side_m, side_m], [0.0, side_m]],
        "north_angle_deg": 0.0,
        "access_edge": 0,
        "core_hint": None,
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_rulebook_for(types: Sequence[str], path: Path) -> Path:
    """The Ticket 3.1 test rulebook, extended with ``types`` (same uniform statistics)."""
    data = yaml.safe_load(RULEBOOK_TEST.read_text(encoding="utf-8"))
    template = data["types"]["office"]
    for key in types:
        data["types"].setdefault(key, dict(template))
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
