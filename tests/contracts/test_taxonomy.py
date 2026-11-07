"""Tests T01-T05: taxonomy loading, integrity, label normalisation, room-type validator."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from ale.contracts.enums import MacroZone, TypeCategory
from ale.contracts.models import RoomSpec
from ale.contracts.taxonomy import TAXONOMY_PATH, UNKNOWN, Taxonomy, canon, load_taxonomy

# raw, canonical_input, key, rule
TABLE = [
    ("S. REUNION", "S REUNION", "meeting_room", "exact"),
    ("Salle de Réunion 2", "SALLE DE REUNION", "meeting_room", "exact"),
    ("Bur.12", "BUR", "office", "exact"),
    ("BUREAU 12,40 m²", "BUREAU", "office", "exact"),
    ("101 BUREAU", "BUREAU", "office", "exact"),
    ("WC H/F", "WC HF", "sanitary", "exact"),
    ("wc h/f 3", "WC HF", "sanitary", "exact"),
    ("S.D.R.", "SDR", "meeting_room", "exact"),
    ("LOCAL TECH.", "LOCAL TECH", "technical_room", "exact"),
    ("Local technique R+1", "LOCAL TECHNIQUE R", "technical_room", "prefix"),
    ("DGT", "DGT", "circulation", "exact"),
    ("OFFICE", "OFFICE", "kitchenette", "exact"),
    ("SALLE", "SALLE", "unknown", "none"),
    ("Bureau paysager nord", "BUREAU PAYSAGER NORD", "open_office", "prefix"),
    ("B12 ARCHIVES", "ARCHIVES", "archive", "exact"),
    ("W.C.", "WC", "sanitary", "exact"),
    ("12,40 m²", "", "unknown", "none"),
    ("", "", "unknown", "none"),
    ("Esc. A", "ESC A", "stair", "prefix"),
    ("Hall d\u2019entrée", "HALL D ENTREE", "entrance_hall", "exact"),
    ("LOC. MÉNAGE", "LOC MENAGE", "cleaning_room", "exact"),
    ("Accueil / attente", "ACCUEIL ATTENTE", "reception", "prefix"),
    ("VESTIAIRES H/F", "VESTIAIRES HF", "locker_room", "exact"),
    ("XYZ", "XYZ", "unknown", "none"),
]


def test_T01_load_valid(h: SimpleNamespace) -> None:
    tax = load_taxonomy()
    assert len(tax.types) == 25
    assert tax.version == "1.0.0"
    assert TAXONOMY_PATH.read_bytes() == (h.TICKET_DIR / "taxonomy.v1.yaml").read_bytes()
    assert load_taxonomy() is tax  # cached
    assert tax.keys()[0] == "office"
    assert tax.keys()[-1] == UNKNOWN
    assert tax.get("stair").category is TypeCategory.VERTICAL
    with pytest.raises(KeyError):
        tax.get("kitchen")
    assert load_taxonomy(TAXONOMY_PATH) == tax  # explicit path, not cached


def _base() -> dict[str, Any]:
    def t(key: str, cat: str, syns: list[str]) -> dict[str, Any]:
        return {
            "key": key,
            "label_fr": key,
            "label_en": key,
            "category": cat,
            "default_macro_zone": None,
            "service_core": False,
            "synonyms": syns,
        }

    return {
        "version": "1.0.0",
        "types": [
            t("office", "ROOM", ["BUREAU"]),
            t("meeting_room", "ROOM", ["SALLE DE REUNION"]),
            t("unknown", "SPECIAL", []),
        ],
    }


def _dup_key(d: dict[str, Any]) -> None:
    d["types"].append(copy.deepcopy(d["types"][0]))


def _shared_synonym(d: dict[str, Any]) -> None:
    d["types"][0]["synonyms"].append("S.REUNION")
    d["types"][1]["synonyms"].append("S.REUNION")


def _missing_unknown(d: dict[str, Any]) -> None:
    d["types"].pop()


def _bad_key(d: dict[str, Any]) -> None:
    d["types"][0]["key"] = "Office"


def _bad_version(d: dict[str, Any]) -> None:
    d["version"] = "v1"


def _no_synonyms(d: dict[str, Any]) -> None:
    d["types"][1]["synonyms"] = []


def _unknown_wrong(d: dict[str, Any]) -> None:
    d["types"][2]["category"] = "ROOM"
    d["types"][2]["synonyms"] = ["XYZ"]


def _empty_canonical(d: dict[str, Any]) -> None:
    d["types"][0]["synonyms"].append("12")


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_dup_key, "duplicate key 'office'"),
        (_shared_synonym, "'S REUNION'"),
        (_missing_unknown, "missing type 'unknown'"),
        (_bad_key, "bad key 'Office'"),
        (_bad_version, "not semver"),
        (_no_synonyms, "'meeting_room' has no synonyms"),
        (_unknown_wrong, "must have category SPECIAL"),
        (_empty_canonical, "empty canonical form"),
    ],
)
def test_T02_integrity_errors(mutate: Any, needle: str, tmp_path: Path) -> None:
    data = _base()
    Taxonomy.model_validate(data)  # the base is valid
    mutate(data)
    with pytest.raises(ValueError, match=r"invalid taxonomy") as exc:
        Taxonomy.model_validate(data)
    assert needle in str(exc.value)
    path = tmp_path / "tax.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid taxonomy"):
        load_taxonomy(path)


def test_T02_lists_every_problem() -> None:
    data = _base()
    _bad_key(data)
    _bad_version(data)
    with pytest.raises(ValueError) as exc:
        Taxonomy.model_validate(data)
    assert "bad key" in str(exc.value)
    assert "not semver" in str(exc.value)


@pytest.mark.parametrize(("raw", "canonical", "key", "rule"), TABLE)
def test_T03_normalisation_table(raw: str, canonical: str, key: str, rule: str) -> None:
    m = load_taxonomy().normalize_label(raw)
    assert (m.key, m.rule) == (key, rule)
    if rule == "none":
        assert m.matched_synonym is None
    else:
        assert m.matched_synonym in load_taxonomy().get(key).synonyms


@pytest.mark.parametrize(("raw", "canonical", "key", "rule"), TABLE)
def test_T04_canonical_forms(raw: str, canonical: str, key: str, rule: str) -> None:
    assert load_taxonomy().normalize_label(raw).canonical_input == canonical
    assert canon(raw) == canonical


def test_T04_canonical_extra_rules() -> None:
    assert canon("BUREAU 12M2") == "BUREAU"  # single-token area
    assert canon("BUREAU 12 m2 3A") == "BUREAU"  # area, then trailing room number
    assert canon("R01 S D R 3A") == "SDR"
    assert canon("BUREAU M2 NORD") == "BUREAU M2 NORD"  # no number before M2: kept


def _room(type_key: str) -> RoomSpec:
    return RoomSpec(
        id="R1", name="Room", type=type_key, target_area_m2=10.0, macro_zone=MacroZone.PUBLIC
    )


def test_T05_room_type_validator() -> None:
    assert _room("office").type == "office"
    for bad in ("kitchen", "unknown", "circulation"):
        with pytest.raises(ValidationError):
            _room(bad)
