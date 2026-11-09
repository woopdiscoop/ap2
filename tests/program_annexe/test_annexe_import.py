"""Ticket P.2: import of a "programme physique" (Annexe format), evals A01-A09.

Every workbook is synthetic (see ``annexe_helpers``); the real AREP-MS Annexe is never used.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from annexe_helpers import (
    AREP_COUNTS,
    HEADER,
    HEADER_VARIANT,
    REGION_BLOCKS,
    REGION_COUNTS,
    Sheet,
    arep_like,
    simple_annexe,
    write_rulebook_for,
    write_site,
)
from typer.testing import CliRunner

from ale.cli import app
from ale.contracts.enums import MacroZone
from ale.program import read_program
from ale.program.annexe import (
    DEFAULT_RULES_PATH,
    AnnexeError,
    entity_code,
    fold_name,
    load_rules,
    match_rule,
    read_annexe,
    slugify,
    write_outputs,
)

openpyxl = pytest.importorskip("openpyxl")  # the 'excel' extra

REPO = Path(__file__).resolve().parents[2]


def _runner() -> CliRunner:
    try:  # click < 8.2 needs mix_stderr=False to expose result.stderr separately
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _import(annexe: Path, out: Path, *extra: str) -> Any:
    args = ["program", "import", "--annexe", str(annexe), "--out", str(out), *extra]
    return _runner().invoke(app, args)


def _mapping(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _counts(building: Any) -> tuple[int, int, float]:
    return len(building.lines), building.instances, float(building.useful_m2)


# --------------------------------------------------------------------------- A01


def test_A01_two_buildings(tmp_path: Path) -> None:
    annexe = arep_like(tmp_path / "annexe.xlsx")
    result = read_annexe(annexe)
    assert [b.name for b in result.buildings] == ["SIEGE DE LA REGION", "AREP"]
    region, arep = result.buildings
    assert _counts(region) == REGION_COUNTS
    assert _counts(arep) == AREP_COUNTS
    assert [(t.building, float(t.stated_m2), t.ok) for t in result.totals] == [
        ("SIEGE DE LA REGION", 492.0, True),
        ("AREP", 246.0, True),
    ]
    assert not result.warnings
    assert not result.unmatched
    assert [(s.espace, s.reason) for s in result.skipped] == [
        ("Parking à ciel ouvert (80 places)", "exclu par une règle")
    ]

    out = tmp_path / "out"
    res = _import(annexe, out)
    assert res.exit_code == 0, res.output
    assert sorted(p.name for p in out.iterdir()) == [
        "arep_mapping.csv",
        "arep_programme.xlsx",
        "siege_de_la_region_mapping.csv",
        "siege_de_la_region_programme.xlsx",
    ]
    text = res.stdout
    assert "Bâtiments : 2" in text
    assert "SIEGE DE LA REGION : 9 lignes, 17 instances, 492.00 m² utiles" in text
    assert "AREP : 5 lignes, 6 instances, 246.00 m² utiles" in text
    assert "Lignes ignorées (1)" in text
    assert "Parking à ciel ouvert" in text
    assert "Contrôle des totaux (2)" in text
    assert "ÉCART" not in text

    rows = _mapping(out / "siege_de_la_region_mapping.csv")
    assert list(rows[0]) == [
        "id",
        "name",
        "entity",
        "type",
        "zone",
        "facade",
        "quantity",
        "area",
    ]
    assert rows[0] == {
        "id": "A01",
        "name": "Hall d'entrée/Accueil — Accueil",
        "entity": "ACCUEIL",
        "type": "entrance_hall",
        "zone": "Public",
        "facade": "Oui",
        "quantity": "1",
        "area": "60",
    }
    assert sum(int(r["quantity"]) for r in rows) == 17


def test_A01_building_filter(tmp_path: Path) -> None:
    annexe = arep_like(tmp_path / "annexe.xlsx")
    out = tmp_path / "out"
    res = _import(annexe, out, "--building", "arep")
    assert res.exit_code == 0, res.output
    assert sorted(p.name for p in out.iterdir()) == ["arep_mapping.csv", "arep_programme.xlsx"]

    res = _import(annexe, tmp_path / "none", "--building", "Inconnu")
    assert res.exit_code == 2
    assert "introuvable" in res.stderr
    assert "SIEGE DE LA REGION" in res.stderr
    assert not (tmp_path / "none").exists()


# --------------------------------------------------------------------------- A02


def test_A02_entity_carry(tmp_path: Path) -> None:
    region = read_annexe(arep_like(tmp_path / "annexe.xlsx")).buildings[0]
    by_espace = {line.espace: line for line in region.lines}
    # Merged ENTITE cells (A5:A7) carry ACCUEIL down to the two following rows.
    assert by_espace["Loge gardien"].entity == "ACCUEIL"
    assert by_espace["Bureau d'ordre"].entity == "ACCUEIL"
    assert by_espace["Salle de prière"].entity == "ESPACE COMMUN"
    assert by_espace["Local technique / Régie"].entity == "ESPACE CONFERENCE"
    assert by_espace["Secrétariat/Attente"].name == (
        "Secrétariat/Attente — Direction des Ressources"
    )
    ids = [line.id for line in region.lines]
    assert ids == ["A01", "A02", "A03", "EC01", "EC02", "EC201", "EC202", "DR01", "DR02"]
    assert len(set(ids)) == len(ids)
    # Same initials: ESPACE COMMUN / ESPACE CONFERENCE get distinct codes.
    assert entity_code("ESPACE COMMUN") == entity_code("ESPACE CONFERENCE") == "EC"


def test_A02_blank_entity_cells_and_codes(tmp_path: Path) -> None:
    s = Sheet()
    s.add("PROGRAMME PHYSIQUE")
    s.add(*HEADER)
    s.add(None, "Salle de réunion", 1, 20, 20)  # no entity yet
    s.add("DIRECTION DE LA COMMUNICATION ET DES AFFAIRES GENERALES INTERNES")
    s.add(None, "Bureau Expert", 1, 12, 12)  # blank (not merged) cells carry the entity
    s.add(None, "Bureau Expert", 1, 12, 12)
    s.add("DIRECTION CENTRALE", "Bureau du Président", 1, 30, 30)
    s.blocks([("DIRECTION COMMUNE", [(f"Bureau {i}", 1, 10) for i in range(1, 4)])], merge=False)
    path = s.save(tmp_path / "a.xlsx")
    b = read_annexe(path).buildings[0]
    assert b.name == "Bâtiment 1"
    assert b.slug == "batiment_1"
    assert [line.id for line in b.lines] == [
        "X01",
        "DCAG01",
        "DCAG02",
        "DC01",
        "DC201",
        "DC202",
        "DC203",
    ]
    assert b.lines[0].name == "Salle de réunion"
    assert b.lines[1].entity.startswith("DIRECTION DE LA COMMUNICATION")
    assert all(len(line.name) <= 120 for line in b.lines)


def test_A02_id_uniqueness_and_long_names(tmp_path: Path) -> None:
    long_entity = "SERVICE " + "TRES LONG " * 15
    lines = [("Bureau", 1, 10)] * 3
    path = simple_annexe(tmp_path / "a.xlsx", [(long_entity, lines), ("SECTION", lines)])
    b = read_annexe(path).buildings[0]
    assert len(b.lines[0].name) <= 120
    assert [line.id for line in b.lines] == ["STLT01", "STLT02", "STLT03", "S01", "S02", "S03"]
    assert slugify("  Siège — Région Marrakech-Safi ") == "siege_region_marrakech_safi"
    assert slugify("—") == "batiment"
    assert entity_code("") == "X"
    assert entity_code("DE LA") == "DL"


# --------------------------------------------------------------------------- A03

#: Every name of the AREP-MS Annexe (accents and case vary) → expected taxonomy type.
AREP_NAMES: list[tuple[str, str | None]] = [
    ("Hall d'entrée/Accueil", "entrance_hall"),
    ("Loge gardien", "security_room"),
    ("Bureau d'ordre", "mail_room"),
    ("Archives", "archive"),
    ("Archives de proximité", "archive"),
    ("Stockage matériel", "storage"),
    ("Stockage de proximité", "storage"),
    ("Salle technique pour serveurs", "it_room"),
    ("Bureau service informatique", "office"),
    ("Sanit.F+PMR", "sanitary"),
    ("sanit.H+PMR", "sanitary"),
    ("Sanitaires", "sanitary"),
    ("Sanitaires H/F", "sanitary"),
    ("Sanit.Hommes/Femmes/PMR", "sanitary"),
    ("Buvette", "bar"),
    ("Local technique - Nettoyage", "cleaning_room"),
    ("Local technique", "technical_room"),
    ("LOCAL TECHNIQUE / RÉGIE", "control_room"),
    ("Local technique / Regie", "control_room"),
    ("Infirmerie", "first_aid_room"),
    ("Salle de prière", "quiet_room"),
    ("Salle Ablutions", "sanitary"),
    ("Salon VIP", "waiting_area"),
    ("Salon / Attente", "waiting_area"),
    ("Salle de réunion", "meeting_room"),
    ("Salles de reunion", "meeting_room"),
    ("Salle de conférence (150 places)", "auditorium"),
    ("Bureau du Directeur", "office"),
    ("Secrétariat", "office"),
    ("Secretariat/Attente", "office"),
    ("Bureau - Chef de Division", "office"),
    ("Bureau - Chef de Service", "office"),
    ("Chef de service", "office"),
    ("Bureaux en open space", "open_office"),
    ("Bureau du Président", "office"),
    ("Arrière bureau", "office"),
    ("Bureau vice président", "office"),
    ("Bureau - Chargé de mission", "office"),
    ("Bureau Chef de département des affaires juridiques", "office"),
    ("Chef de département du patrimoine", "office"),
    ("Département de la coopération", "office"),
    ("Bureaux administratifs", "office"),
    ("Coordination Direction", "office"),
    ("Cellule communication", "office"),
    ("Bureau Expert", "office"),
    ("Local pour chauffeurs", "staff_room"),
    ("Parking à ciel ouvert (80 places)", None),
    ("Parking souterrain", None),
    ("PARKING VISITEURS", None),
    ("Salle d'attente", "waiting_area"),
    ("Rangement", "storage"),
    ("WC", "sanitary"),
    ("Cafétéria", "bar"),
    ("Local ménage", "cleaning_room"),
    ("Plateau de bureaux", "open_office"),
    ("Directeur adjoint", "office"),
]


def test_A03_mapping() -> None:
    rules = load_rules()
    hit: set[int] = set()
    for name, expected in AREP_NAMES:
        rule = match_rule(name, rules)
        assert rule is not None, name
        assert rule.type == expected, (name, rule.type, expected)
        hit.add(rule.index)
    assert hit == set(range(len(rules))), "every default rule is exercised"
    # First match wins.
    regie = match_rule("Local technique / Régie", rules)
    assert regie is not None
    assert regie.type == "control_room"
    ordre = match_rule("Bureau d'ordre", rules)
    assert ordre is not None
    assert ordre.type == "mail_room"
    assert match_rule("Piscine", rules) is None
    assert fold_name("  Hall  D'ENTRÉE ") == "hall d'entree"


def test_A03_zones_and_facades(tmp_path: Path) -> None:
    region = read_annexe(arep_like(tmp_path / "annexe.xlsx")).buildings[0]
    by_espace = {line.espace: line for line in region.lines}
    office = by_espace["Bureau - Chef de Service"]
    assert (office.type, office.zone, office.facade) == ("office", MacroZone.ADMINISTRATIVE, True)
    wc = by_espace["Sanitaires H/F"]
    assert (wc.type, wc.zone, wc.facade, wc.quantity) == ("sanitary", MacroZone.SERVICES, False, 2)
    assert by_espace["Bureau d'ordre"].type == "mail_room"
    assert by_espace["Local technique / Régie"].type == "control_room"


# --------------------------------------------------------------------------- A04


def test_A04_unmatched(tmp_path: Path) -> None:
    blocks = [*REGION_BLOCKS, ("LOISIRS", [("Piscine olympique", 1, 500), ("Sauna", 1, 20)])]
    annexe = arep_like(tmp_path / "annexe.xlsx", region_blocks=blocks, region_total=1012)
    out = tmp_path / "out"
    res = _import(annexe, out)
    assert res.exit_code == 2
    assert "« Piscine olympique »" in res.stderr
    assert "« Sauna »" in res.stderr
    assert "sans règle de correspondance (2)" in res.stderr
    assert "Aucun fichier écrit" in res.stderr
    assert not out.exists()
    result = read_annexe(annexe)
    assert [(u.espace, u.building) for u in result.unmatched] == [
        ("Piscine olympique", "SIEGE DE LA REGION"),
        ("Sauna", "SIEGE DE LA REGION"),
    ]


# --------------------------------------------------------------------------- A05


def test_A05_custom_rules(tmp_path: Path) -> None:
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "- {match: 'salle de priere', type: meeting_room, zone: Administratif, facade: true}\n"
        "- {match: 'chauffeur', type: null}\n",
        encoding="utf-8",
    )
    annexe = arep_like(tmp_path / "annexe.xlsx")
    out = tmp_path / "out"
    res = _import(annexe, out, "--rules", str(rules))
    assert res.exit_code == 0, res.output
    region = {r["name"]: r for r in _mapping(out / "siege_de_la_region_mapping.csv")}
    priere = region["Salle de prière — Espace Commun"]
    assert (priere["type"], priere["zone"], priere["facade"]) == (
        "meeting_room",
        "Administratif",
        "Oui",
    )
    # The other defaults still apply after the custom rules.
    assert region["Bureau d'ordre — Accueil"]["type"] == "mail_room"
    arep = _mapping(out / "arep_mapping.csv")
    assert all("chauffeurs" not in r["name"] for r in arep)
    assert "Local pour chauffeurs (exclu par une règle)" in res.stdout
    # Excluded rows with a numeric surface still count in the stated total (246).
    assert "ÉCART" not in res.stdout


def test_A05_rules_replace_and_errors(tmp_path: Path) -> None:
    only = tmp_path / "only.yaml"
    only.write_text(
        "include_defaults: false\nrules:\n  - {match: '.', type: office}\n", encoding="utf-8"
    )
    rules = load_rules(only)
    assert len(rules) == 1
    assert rules[0].zone is None
    path = simple_annexe(tmp_path / "a.xlsx", [("E", [("Parking", 1, 10), ("WC", 1, 4)])])
    b = read_annexe(path, rules).buildings[0]
    assert {line.type for line in b.lines} == {"office"}
    assert {line.zone for line in b.lines} == {MacroZone.ADMINISTRATIVE}  # taxonomy default

    bad_cases = {
        "a: [": "illisible",
        "42": "liste de règles",
        "- 3": "objet",
        "- {match: 'x', type: office, colour: red}": "clés inconnues",
        "- {match: '', type: office}": "non vide",
        "- {match: '(', type: office}": "invalide",
        "- {match: 'x', type: spaceship}": "type inconnu",
        "- {match: 'x', type: circulation}": "non autorisé",
        "- {match: 'x', type: office, zone: Lune}": "zone inconnue",
        "- {match: 'x', type: office, facade: peut-etre}": "true ou false",
    }
    for i, (content, needle) in enumerate(bad_cases.items()):
        bad = tmp_path / f"bad{i}.yaml"
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(AnnexeError, match=needle):
            load_rules(bad)
    with pytest.raises(AnnexeError, match="illisible"):
        load_rules(tmp_path / "absent.yaml")

    ok = tmp_path / "ok.yaml"
    ok.write_text("- {match: 'x', type: office, zone: SERVICES, facade: null}\n", encoding="utf-8")
    first = load_rules(ok)[0]
    assert (first.zone, first.facade, first.index) == (MacroZone.SERVICES, False, 0)
    assert load_rules(ok)[1].index == 1  # defaults follow, re-indexed

    res = _import(path, tmp_path / "out", "--rules", str(tmp_path / "bad1.yaml"))
    assert res.exit_code == 2
    assert "ERREUR" in res.stderr
    assert DEFAULT_RULES_PATH.is_file()


# --------------------------------------------------------------------------- A06


def test_A06_round_trip(tmp_path: Path) -> None:
    annexe = arep_like(tmp_path / "annexe.xlsx")
    out = tmp_path / "out"
    assert _import(annexe, out).exit_code == 0
    result = read_annexe(annexe)
    programs = sorted(out.glob("*_programme.xlsx"))
    assert len(programs) == 2
    types: set[str] = set()
    for building in result.buildings:
        xlsx = out / f"{building.slug}_programme.xlsx"
        program, report = read_program(xlsx)
        assert report.errors == (), report.errors
        assert program is not None
        assert program == building.program()
        assert all(r.floor == 0 for r in program.rooms)
        types |= {r.type for r in program.rooms}

    site = write_site(tmp_path / "site.yaml")
    rulebook = write_rulebook_for(sorted(types), tmp_path / "rulebook.yaml")
    for xlsx in programs:
        args = ["program", "check", "--program", str(xlsx), "--site", str(site)]
        res = _runner().invoke(app, [*args, "--rulebook", str(rulebook)])
        assert res.exit_code == 0, res.output
        assert res.stdout.rstrip().endswith("OK")
        assert "Erreurs (0)" in res.stdout


def test_A06_write_outputs_api(tmp_path: Path) -> None:
    result = read_annexe(arep_like(tmp_path / "annexe.xlsx"))
    written = write_outputs(result.buildings[1:], tmp_path / "deep" / "out")
    assert [p.name for p in written] == ["arep_programme.xlsx", "arep_mapping.csv"]
    wb = openpyxl.load_workbook(written[0])
    assert {"Programme", "Exemple", "Aide", "Listes"} <= set(wb.sheetnames)


# --------------------------------------------------------------------------- A07


def test_A07_totals_mismatch(tmp_path: Path) -> None:
    annexe = arep_like(tmp_path / "annexe.xlsx", region_total=502)
    result = read_annexe(annexe)
    region_check = result.totals[0]
    assert not region_check.ok
    assert region_check.stated_m2 - region_check.computed_m2 == Decimal(10)
    assert result.totals[1].ok
    assert len(result.warnings) == 1
    assert "502.00" in result.warnings[0]
    assert "492.00" in result.warnings[0]

    out = tmp_path / "out"
    res = _import(annexe, out)
    assert res.exit_code == 0, res.output
    assert "ÉCART" in res.stdout
    assert "Avertissements (1)" in res.stdout
    assert (out / "siege_de_la_region_programme.xlsx").is_file()

    # Within 0.5 m²: no warning.
    assert read_annexe(arep_like(tmp_path / "b.xlsx", region_total=492.4)).totals[0].ok


def test_A07_subtotals_and_grand_total(tmp_path: Path) -> None:
    s = Sheet()
    s.add("PROGRAMME PHYSIQUE : B")
    s.add(*HEADER)
    s.blocks([("A", [("Bureau", 2, 10)])])
    s.add("TOTAL ENTITE A", None, None, None, "20")  # numeric text
    s.blocks([("B", [("Archives", 1, 5)])])
    s.add("TOTAL ENTITE B", None, None, None, 5)
    s.add("TOTAL SUPERFICIE UTILE", None, None, None, 25)  # grand total: building sum
    s.add("TOTAL SANS VALEUR")
    path = s.save(tmp_path / "t.xlsx")
    result = read_annexe(path)
    assert [(float(t.stated_m2), float(t.computed_m2), t.ok) for t in result.totals] == [
        (20.0, 20.0, True),
        (5.0, 5.0, True),
        (25.0, 25.0, True),
    ]


# --------------------------------------------------------------------------- A08


def test_A08_robustness(tmp_path: Path) -> None:
    blocks = [
        ("ACCUEIL", [("Hall d'entrée/Accueil", "1", "60")]),
        ("ESPACE COMMUN", [("Sanitaires H/F", 2.0, "20,5"), ("Salle de prière", 1, 30.0)]),
    ]
    s = Sheet()
    s.add("programme physique — Bâtiment Sud")
    s.add()
    s.add(None, *HEADER_VARIANT)  # header shifted by one column, accent/case variants
    shifted = Sheet()
    shifted.blocks(blocks)
    for row in shifted.rows:
        s.add(None, *row)
        s.add()  # empty rows in between
    s.add(None, "ESPACE COMMUN", "Infirmerie", 1, None)  # empty surface → skipped
    s.add(None, None, "Bureau", 0, 12)  # nombre 0 → skipped
    s.add(None, None, "Bureau", "deux", 12)  # nombre text → skipped
    s.add(None, None, None, 3, 3)  # no espace → ignored
    s.add("PROGRAMME PHYIQUE")
    s.add(*HEADER)
    s.add("SERVICES", "Archives", 1, 16)
    path = s.save(tmp_path / "robust.xlsx")

    result = read_annexe(path)
    sud, unnamed = result.buildings
    assert sud.name == "Bâtiment Sud"
    assert [(line.espace, line.quantity, float(line.area_m2)) for line in sud.lines] == [
        ("Hall d'entrée/Accueil", 1, 60.0),
        ("Sanitaires H/F", 2, 20.5),
        ("Salle de prière", 1, 30.0),
    ]
    assert unnamed.name == "Bâtiment 2"
    assert unnamed.lines[0].type == "archive"
    reasons = [s.reason for s in result.skipped]
    assert reasons[0] == "surface unitaire non numérique (vide)"
    assert reasons[1].startswith("nombre invalide")
    assert reasons[2] == "nombre invalide (« deux »)"

    res = _import(path, tmp_path / "out")
    assert res.exit_code == 0, res.output
    assert (tmp_path / "out" / "batiment_sud_programme.xlsx").is_file()
    assert (tmp_path / "out" / "batiment_2_programme.xlsx").is_file()


def test_A08_typo_title_and_text_numbers(tmp_path: Path) -> None:
    annexe = arep_like(tmp_path / "annexe.xlsx", arep_header=HEADER_VARIANT)
    wb = openpyxl.load_workbook(annexe)
    ws = wb.active
    for row in ws.iter_rows():
        if row[1].value == "Bureau - Chef de Service":
            row[2].value, row[3].value = "8", "16"
    wb.save(annexe)
    result = read_annexe(annexe)
    assert [b.name for b in result.buildings] == ["SIEGE DE LA REGION", "AREP"]
    assert _counts(result.buildings[0]) == REGION_COUNTS
    assert _counts(result.buildings[1]) == AREP_COUNTS


def test_A08_no_header(tmp_path: Path) -> None:
    s = Sheet()
    s.add("PROGRAMME PHYSIQUE")
    s.add("ESPACE", "SURFACE")
    s.add("Bureau", 12)
    path = s.save(tmp_path / "noheader.xlsx")
    out = tmp_path / "out"
    res = _import(path, out)
    assert res.exit_code == 2
    assert "aucune ligne d'en-tête" in res.stderr
    assert "ESPACE, NOMBRE et SURFACE UNITAIRE" in res.stderr
    assert not out.exists()

    bad = tmp_path / "not_excel.xlsx"
    bad.write_text("not a workbook", encoding="utf-8")
    res = _import(bad, out)
    assert res.exit_code == 2
    assert "Classeur illisible" in res.stderr
    res = _import(tmp_path / "absent.xlsx", out)
    assert res.exit_code == 2

    # A header but every row excluded: nothing to import.
    only_parking = simple_annexe(tmp_path / "p.xlsx", [("P", [("Parking", 1, 100)])])
    result = read_annexe(only_parking)
    assert result.buildings == []
    assert "sans ligne importée" in result.warnings[0]
    res = _import(only_parking, out)
    assert res.exit_code == 2
    assert "aucune ligne de programme" in res.stderr


def test_A08_second_sheet_and_notes_before_header(tmp_path: Path) -> None:
    path = tmp_path / "two_sheets.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Garde"
    wb.active.append(["Page de garde"])
    ws = wb.create_sheet("Annexe 3")
    ws.append(["NB : document indicatif du programme physique"])  # a note, not a title
    ws.append(["TOTAL 12"])  # before any header: ignored
    ws.append(HEADER)
    ws.append(["E", "Bureau", 1, 12, 12])
    wb.save(path)
    result = read_annexe(path)
    assert [b.name for b in result.buildings] == ["Bâtiment 1"]
    assert result.totals == []


# --------------------------------------------------------------------------- A09


def test_A09_gates() -> None:
    """Contracts are untouched (lock check); ruff/mypy/coverage run in CI (see eval report)."""
    lock = subprocess.run(
        [sys.executable, "-m", "ale.contracts.lock", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert lock.returncode == 0, lock.stdout + lock.stderr
    rules = DEFAULT_RULES_PATH.read_text(encoding="utf-8")
    assert "parking" in rules


def test_A08_duplicate_building_names(tmp_path: Path) -> None:
    s = Sheet()
    for _ in range(2):
        s.add("PROGRAMME PHYSIQUE : Annexe")
        s.add(*HEADER)
        s.add("E", "Bureau", 1, 12, 12)
    result = read_annexe(s.save(tmp_path / "dup.xlsx"))
    assert [b.slug for b in result.buildings] == ["annexe", "annexe_2"]
