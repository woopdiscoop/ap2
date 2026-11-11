"""Ticket R.3 evaluation S306-S307: the space-syntax section of ``report.md`` and the
unchanged layout / DXF / SVG outputs."""

from __future__ import annotations

import hashlib
import re
from fractions import Fraction
from pathlib import Path

import ezdxf
from export_helpers import make_layout

from ale.analysis import analyse
from ale.config import AleConfig
from ale.contracts.models import Layout
from ale.export import RunFiles, export_run
from ale.program.models import PreparedInput

HEADING = "### Lecture spatiale (space syntax)"
FR_NUM = re.compile(r"-?\d+,\d{2}")


def _export(layout: Layout, prepared: PreparedInput, out: Path) -> RunFiles:
    return export_run(layout, prepared, out, rulebook_version="test-3.1", run_id="run-001")


def _fr(x: Fraction) -> str:
    return f"{float(x):.2f}".replace(".", ",")


def _syntax_block(text: str) -> list[str]:
    lines = text.splitlines()
    return [ln for ln in lines[lines.index(HEADING) + 1 :] if ln.strip()]


def _rows(block: list[str]) -> list[list[str]]:
    return [[c.strip() for c in ln.strip("|").split("|")] for ln in block if ln.startswith("|")]


def test_S306_report(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    assert text.count(HEADING) == 1
    block = _syntax_block(text)
    rows = _rows(block)
    syn = analyse(layout, prepared, AleConfig())
    # per-room table: header, separator, one row per room
    assert rows[0] == [
        "ID",
        "Nom",
        "Profondeur",
        "Intégration",
        "Contrôle",
        "Distance depuis l'entrée m",
    ]
    rooms = rows[2 : 2 + len(layout.rooms)]
    assert [r[0] for r in rooms] == [p.instance_id for p in layout.rooms]
    for row, r in zip(rooms, syn.rooms, strict=True):
        assert row[2] == (str(r.depth) if r.depth is not None else "—")
        assert row[3] == (_fr(r.integration) if r.integration is not None else "—")
        assert row[4] == _fr(r.control)
        assert row[5] == (_fr(r.walk_m) if r.walk_m is not None else "—")
        for cell in row[3:]:
            assert cell == "—" or FR_NUM.fullmatch(cell), cell  # French format, no "."
    assert rooms[0][:2] == ["R01", "Hall d'entrée"]
    assert rooms[0][3:] == ["4,67", "0,62", "4,70"]  # 5/8 -> half-even
    assert rooms[6][2:] == ["—", "—", "0,00", "—"]  # R06: no door on the corridor
    # zone means
    zones = rows[2 + len(layout.rooms) :]
    assert zones[0] == ["Zone", "Profondeur moyenne"]
    assert [z[0] for z in zones[2:]] == ["Public", "Administratif", "Services"]
    assert all(z[1] == "2,00" for z in zones[2:])
    # layout-level lines and the two generated sentences
    assert "- Profondeur moyenne : 2,00" in block
    assert "- Distance maximale depuis l'entrée : 5,35 m" in block
    assert "- Entrée inférée : oui" in block
    assert block[-2] == (
        "La pièce la plus intégrée est Hall d'entrée (intégration 4,67); "
        "la plus profonde est Hall d'entrée (profondeur 2)."
    )
    assert block[-1] == (
        "La profondeur moyenne des pièces publiques (2,00) est égale à "
        "celle des pièces administratives (2,00)."
    )


def test_S306_existing_sections_untouched(
    tmp_path: Path, layout: Layout, prepared: PreparedInput
) -> None:
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    heads = [ln for ln in text.splitlines() if ln.startswith("# ") or ln.startswith("## ")]
    assert heads == [
        "# Rapport de génération — run-001",
        "## Résumé",
        "## Surfaces",
        "## Contraintes non respectées",
        "## Coût",
        "## Fichiers",
    ]
    assert text.index(HEADING) > text.index("## Fichiers")


def test_S306_sentence_variants(tmp_path: Path, prepared: PreparedInput) -> None:
    # No circulation: nothing integrated, nothing reached; comparison impossible.
    layout = make_layout().model_copy(update={"circulation": ()})
    text = _export(layout, prepared, tmp_path).report_md.read_text(encoding="utf-8")
    block = _syntax_block(text)
    assert block[-2] == "Aucune intégration n'est définie."
    assert block[-1] == (
        "La profondeur moyenne des pièces publiques et administratives ne peut pas être comparée."
    )
    assert "- Profondeur moyenne : —" in block
    assert "- Distance maximale depuis l'entrée : — m" in block


S307_JSON = "48c2bcbd0d8bbecbf6814680d32f05aa37818d1efb2a22dd3383c9333b621a44"
S307_SVG = "e87290416463727eb2862950c5b825113aff3ce2fa0c1c4b8ccf2c6f10fdb24c"
#: DXF content (layers, then every entity: kind, layer, geometry). The DXF file itself is not
#: byte-stable even for identical input (ezdxf timestamps, GUIDs and object order vary per
#: process), so its content is hashed instead.
S307_DXF = "ff3a360ee997561c65d736891ccb7fba932ec751520363a24f9e3198945c89a8"


def _dxf_content(path: Path) -> str:
    doc = ezdxf.readfile(path)
    rows: list[str] = [f"layer {la.dxf.name} {la.dxf.color}" for la in doc.layers]
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind == "LWPOLYLINE":
            geo = repr(tuple(tuple(p) for p in e.get_points("xy")))
        elif kind == "MTEXT":
            geo = repr((e.text, tuple(e.dxf.insert)))
        else:
            geo = repr((tuple(e.dxf.start), tuple(e.dxf.end)))
        rows.append(f"{kind} {e.dxf.layer} {geo}")
    return "\n".join(sorted(rows))


def test_S307_unchanged(tmp_path: Path, layout: Layout, prepared: PreparedInput) -> None:
    """Hashes measured before the report change on the export fixture (P8 / small site)."""
    files = _export(layout, prepared, tmp_path)
    assert hashlib.sha256(files.layout_json.read_bytes()).hexdigest() == S307_JSON
    assert hashlib.sha256(files.preview_svg.read_bytes()).hexdigest() == S307_SVG
    assert files.layout_dxf is not None
    assert hashlib.sha256(_dxf_content(files.layout_dxf).encode()).hexdigest() == S307_DXF
