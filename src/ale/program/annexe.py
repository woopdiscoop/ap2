"""Import a public-tender "programme physique" spreadsheet (Annexe format) (Ticket P.2).

The sheet holds one or more building sections (title rows ``PROGRAMME PHYSIQUE …``), each
with a header row ``ENTITE | ESPACE | NOMBRE | SURFACE UNITAIRE | SURFACE TOTALE`` (detected
case- and accent-insensitively), data rows, totals and notes. :func:`read_annexe` maps every
espace to a taxonomy type with ordered regex rules (:func:`load_rules`) and returns one ALE
program per building; :func:`write_outputs` writes each one as an ALE template plus a mapping
CSV. Areas are m². Requires the ``excel`` extra (openpyxl).
"""

from __future__ import annotations

import csv
import dataclasses
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from ale.contracts.enums import MacroZone, TypeCategory
from ale.contracts.models import Program, RoomSpec
from ale.contracts.taxonomy import load_taxonomy
from ale.program.excel import SHEET_NAME, ZONE_LABELS, canon_header

__all__ = [
    "DEFAULT_RULES_PATH",
    "AnnexeBuilding",
    "AnnexeError",
    "AnnexeLine",
    "AnnexeResult",
    "AnnexeRule",
    "SkippedRow",
    "TotalCheck",
    "Unmatched",
    "entity_code",
    "fold_name",
    "load_rules",
    "match_rule",
    "read_annexe",
    "slugify",
    "write_outputs",
]

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "data" / "annexe_rules.yaml"

#: Stated total vs. sum of the read rows: tolerated gap (m²).
TOTAL_TOLERANCE_M2 = Decimal("0.5")

_NAME_MAX = 120
_CODE_MAX = 4
_TITLE_RE = re.compile(r"programme\s+phys?ique", re.IGNORECASE)
_NOTE_RE = re.compile(r"^(?:total|\(\+\)|n\.?\s?b\.?\s*:)")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset(
    {"a", "au", "aux", "d", "de", "des", "du", "en", "et", "l", "la", "le", "les", "pour", "sur"}
)
_ZONE_WORDS: dict[str, MacroZone] = {
    **{label.casefold(): zone for zone, label in ZONE_LABELS.items()},
    **{zone.name.casefold(): zone for zone in MacroZone},
}
_ALLOWED_CATEGORIES = (TypeCategory.ROOM, TypeCategory.VERTICAL)


class AnnexeError(Exception):
    """The Annexe or the rules file cannot be used (French message)."""


@dataclass(frozen=True)
class AnnexeRule:
    """One mapping rule: ``pattern`` searched in the folded espace name."""

    pattern: re.Pattern[str]
    type: str | None
    zone: MacroZone | None = None
    facade: bool = False
    index: int = 0


@dataclass(frozen=True)
class AnnexeLine:
    """One program line read from the Annexe (``area_m2`` is the unit area)."""

    id: str
    name: str
    espace: str
    entity: str
    type: str
    zone: MacroZone
    facade: bool
    quantity: int
    area_m2: Decimal
    row: int


@dataclass(frozen=True)
class SkippedRow:
    """A row with an espace that is not imported (exclusion rule, text surface, ...)."""

    building: str
    row: int
    espace: str
    reason: str


@dataclass(frozen=True)
class TotalCheck:
    """A stated total compared with the sum of the rows read."""

    building: str
    row: int
    label: str
    stated_m2: Decimal
    computed_m2: Decimal

    @property
    def ok(self) -> bool:
        return abs(self.stated_m2 - self.computed_m2) <= TOTAL_TOLERANCE_M2


@dataclass(frozen=True)
class Unmatched:
    """An espace that no rule matches."""

    building: str
    row: int
    espace: str


@dataclass
class AnnexeBuilding:
    """One building section and its program lines."""

    name: str
    slug: str
    lines: list[AnnexeLine] = field(default_factory=list)

    @property
    def instances(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def useful_m2(self) -> Decimal:
        return sum((line.area_m2 * line.quantity for line in self.lines), Decimal(0))

    def program(self) -> Program:
        """The ALE program of this building (every room on floor 0)."""
        return Program(
            rooms=tuple(
                RoomSpec(
                    id=line.id,
                    name=line.name,
                    type=line.type,
                    target_area_m2=float(line.area_m2),
                    quantity=line.quantity,
                    macro_zone=line.zone,
                    needs_facade=line.facade,
                )
                for line in self.lines
            )
        )


@dataclass
class AnnexeResult:
    """Everything read from an Annexe file."""

    buildings: list[AnnexeBuilding] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    totals: list[TotalCheck] = field(default_factory=list)
    unmatched: list[Unmatched] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- text helpers


def fold_name(text: str) -> str:
    """Lower-case, accent-free, whitespace-collapsed form of ``text`` (rules match on it)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def slugify(text: str) -> str:
    """File-name slug: folded, non-alphanumeric runs → ``_`` (``batiment`` if empty)."""
    slug = _NON_ALNUM_RE.sub("_", fold_name(text)).strip("_")[:60].strip("_")
    return slug or "batiment"


def _words(text: str) -> list[str]:
    return [w for w in _NON_ALNUM_RE.split(fold_name(text)) if w]


def entity_code(entity: str) -> str:
    """Initials of the significant words of ``entity`` (≤ 4 upper-case letters)."""
    words = [w for w in _words(entity) if w not in _STOPWORDS] or _words(entity)
    code = "".join(w[0] for w in words)[:_CODE_MAX].upper()
    return code or "X"


def _title_case(text: str) -> str:
    out = []
    for i, word in enumerate(text.lower().split()):
        if i and fold_name(word) in _STOPWORDS:
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def _text(value: object) -> str | None:
    if isinstance(value, str):
        text = " ".join(value.split())
        return text or None
    return None


def _number(value: object) -> Decimal | None:
    """Exact value of a numeric cell (``"16"`` and ``"12,5"`` accepted), else ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        d = Decimal(str(value))
        return d if d.is_finite() else None
    if isinstance(value, str):
        text = value.strip().replace("\u00a0", "").replace(" ", "")
        if _NUMBER_RE.match(text):
            return Decimal(text.replace(",", "."))
    return None


# --------------------------------------------------------------------------- rules


def _rule_error(source: Path, n: int, message: str) -> AnnexeError:
    return AnnexeError(f"Règles {source} : règle {n} : {message}")


def _parse_rule(raw: object, n: int, source: Path) -> AnnexeRule:
    if not isinstance(raw, dict):
        raise _rule_error(source, n, "un objet {match, type, zone, facade} est attendu.")
    unknown = set(raw) - {"match", "type", "zone", "facade"}
    if unknown:
        raise _rule_error(source, n, f"clés inconnues : {', '.join(sorted(map(str, unknown)))}.")
    match = raw.get("match")
    if not isinstance(match, str) or not match.strip():
        raise _rule_error(source, n, "« match » doit être une expression régulière non vide.")
    try:
        pattern = re.compile(match)
    except re.error as exc:
        raise _rule_error(source, n, f"expression régulière invalide ({exc}).") from exc
    type_key = raw.get("type")
    if type_key is not None:
        tax = load_taxonomy()
        if not isinstance(type_key, str) or type_key not in set(tax.keys()):
            raise _rule_error(source, n, f"type inconnu de la taxonomie : {type_key!r}.")
        if tax.get(type_key).category not in _ALLOWED_CATEGORIES:
            raise _rule_error(source, n, f"type non autorisé dans un programme : {type_key}.")
    zone_raw = raw.get("zone")
    zone: MacroZone | None = None
    if zone_raw is not None:
        zone = _ZONE_WORDS.get(str(zone_raw).strip().casefold())
        if zone is None:
            raise _rule_error(source, n, f"zone inconnue : {zone_raw!r}.")
    facade = raw.get("facade", False)
    if facade is None:
        facade = False
    if not isinstance(facade, bool):
        raise _rule_error(source, n, f"« facade » doit valoir true ou false : {facade!r}.")
    return AnnexeRule(pattern=pattern, type=type_key, zone=zone, facade=facade, index=n - 1)


def _read_rule_list(source: Path) -> tuple[list[object], bool]:
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise AnnexeError(f"Fichier de règles illisible : {source} ({exc}).") from exc
    include_defaults = True
    if isinstance(data, dict):
        include_defaults = bool(data.get("include_defaults", True))
        data = data.get("rules")
    if not isinstance(data, list):
        raise AnnexeError(f"Règles {source} : une liste de règles est attendue.")
    return data, include_defaults


def load_rules(path: Path | None = None) -> tuple[AnnexeRule, ...]:
    """Mapping rules: the shipped defaults, or ``path`` placed before them.

    A rules file is a list of ``{match, type, zone, facade}`` (it takes precedence over the
    defaults, which still apply after it), or a mapping ``{rules: [...], include_defaults:
    false}`` to replace the defaults. Raises :class:`AnnexeError` (French) on a bad file.
    """
    sources = [DEFAULT_RULES_PATH]
    raw: list[tuple[object, int, Path]] = []
    if path is not None:
        custom, include_defaults = _read_rule_list(Path(path))
        raw += [(r, n, Path(path)) for n, r in enumerate(custom, start=1)]
        if not include_defaults:
            sources = []
    for source in sources:
        rules, _ = _read_rule_list(source)
        raw += [(r, n, source) for n, r in enumerate(rules, start=1)]
    return tuple(
        dataclasses.replace(_parse_rule(item, n, source), index=i)
        for i, (item, n, source) in enumerate(raw)
    )


def match_rule(espace: str, rules: Sequence[AnnexeRule]) -> AnnexeRule | None:
    """First rule whose pattern is found in the folded ``espace`` (``None`` if none)."""
    folded = fold_name(espace)
    for rule in rules:
        if rule.pattern.search(folded):
            return rule
    return None


# --------------------------------------------------------------------------- reading


@dataclass
class _Columns:
    espace: int
    nombre: int
    unit: int
    entity: int | None = None
    total: int | None = None


def _header_columns(cells: Sequence[Any]) -> _Columns | None:
    found: dict[str, int] = {}
    for i, value in enumerate(cells):
        text = _text(value)
        if text is None:
            continue
        h = canon_header(text)
        if h in ("espace", "espaces"):
            found.setdefault("espace", i)
        elif h in ("nombre", "nbre", "nb"):
            found.setdefault("nombre", i)
        elif h.startswith("surface unitaire"):
            found.setdefault("unit", i)
        elif h.startswith("surface totale"):
            found.setdefault("total", i)
        elif h in ("entite", "entites"):
            found.setdefault("entity", i)
    if not {"espace", "nombre", "unit"} <= set(found):
        return None
    return _Columns(
        espace=found["espace"],
        nombre=found["nombre"],
        unit=found["unit"],
        entity=found.get("entity"),
        total=found.get("total"),
    )


def _title(cells: Sequence[Any]) -> str | None:
    """Building name if the row is a ``PROGRAMME PHYSIQUE …`` title (``""`` if unnamed)."""
    for value in cells:
        text = _text(value)
        if text is None:
            continue
        m = _TITLE_RE.search(text)
        if m is not None:
            return text[m.end() :].strip(" :-\u2013\u2014_.,;").strip()
    return None


def _cell(cells: Sequence[Any], i: int | None) -> Any:
    if i is None or i >= len(cells):
        return None
    return cells[i]


def _load_sheet_rows(path: Path) -> list[tuple[Any, ...]]:
    import openpyxl  # type: ignore[import-untyped,unused-ignore]

    try:
        wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    except Exception as exc:  # any openpyxl / zip / OS failure
        raise AnnexeError(f"Classeur illisible : {path} ({type(exc).__name__}: {exc}).") from exc
    try:
        for name in wb.sheetnames:
            rows = [tuple(r) for r in wb[name].iter_rows(values_only=True)]
            if any(_header_columns(r) is not None for r in rows):
                return rows
    finally:
        wb.close()
    raise AnnexeError(
        f"{path} : aucune ligne d'en-tête trouvée (colonnes ESPACE, NOMBRE et "
        "SURFACE UNITAIRE attendues)."
    )


class _Reader:
    """Row-by-row state machine over the sheet."""

    def __init__(self, rules: Sequence[AnnexeRule]) -> None:
        self.rules = rules
        self.result = AnnexeResult()
        self.building: AnnexeBuilding | None = None
        self.columns: _Columns | None = None
        self.entity = ""
        self.codes: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.building_sum = Decimal(0)
        self.segment_sum = Decimal(0)
        self.after_circulation = False

    # -- sections
    def start_building(self, name: str) -> None:
        if not name:
            name = f"Bâtiment {len(self.result.buildings) + 1}"
        slug = slugify(name)
        taken = {b.slug for b in self.result.buildings}
        base, k = slug, 2
        while slug in taken:
            slug, k = f"{base}_{k}", k + 1
        self.building = AnnexeBuilding(name=name, slug=slug)
        self.result.buildings.append(self.building)
        self.columns = None
        self.entity = ""
        self.codes = {}
        self.counters = {}
        self.building_sum = Decimal(0)
        self.segment_sum = Decimal(0)
        self.after_circulation = False

    def current(self) -> AnnexeBuilding:
        if self.building is None:
            self.start_building("")
        assert self.building is not None
        return self.building

    # -- ids
    def next_id(self, entity: str) -> str:
        code = self.codes.get(entity)
        if code is None:
            base = entity_code(entity)
            used = set(self.codes.values())
            code, k = base, 2
            while code in used:
                code, k = f"{base}{k}", k + 1
            self.codes[entity] = code
        ids = {line.id for line in self.current().lines}
        while True:  # "EC" + 201 and "EC2" + 01 would clash: skip taken ids
            self.counters[code] = self.counters.get(code, 0) + 1
            rid = f"{code}{self.counters[code]:02d}"
            if rid not in ids:
                return rid

    # -- rows
    def feed(self, n: int, cells: tuple[Any, ...]) -> None:
        if all(_text(c) is None and _number(c) is None for c in cells):
            return
        first = next((t for t in map(_text, cells) if t is not None), None)
        if first is not None and _NOTE_RE.match(fold_name(first)):
            if self.columns is not None:
                self.note(n, first, cells)
            return
        title = _title(cells)
        if title is not None:
            self.start_building(title)
            return
        columns = _header_columns(cells)
        if columns is not None:
            self.current()
            self.columns = columns
            self.entity = ""
            return
        if self.columns is not None:  # rows before the first header are titles/notes
            self.data(n, cells, self.columns)

    def note(self, n: int, label: str, cells: tuple[Any, ...]) -> None:
        folded = fold_name(label)
        if folded.startswith("(+)"):
            self.after_circulation = True
            return
        if not folded.startswith("total") or self.after_circulation:
            return
        numbers = [d for d in map(_number, cells) if d is not None]
        if not numbers:
            return
        stated = numbers[-1]
        building = self.current()
        computed = self.segment_sum
        if abs(stated - computed) > TOTAL_TOLERANCE_M2 and (
            abs(stated - self.building_sum) <= TOTAL_TOLERANCE_M2
        ):
            computed = self.building_sum
        check = TotalCheck(building.name, n, label, stated, computed)
        self.result.totals.append(check)
        if not check.ok:
            self.result.warnings.append(
                f"{building.name}, ligne {n} : total déclaré {_fmt(stated)} m², somme des "
                f"lignes lues {_fmt(computed)} m² (écart {_fmt(stated - computed)} m²)."
            )
        self.segment_sum = Decimal(0)

    def data(self, n: int, cells: tuple[Any, ...], cols: _Columns) -> None:
        entity_cell = _text(_cell(cells, cols.entity))
        if entity_cell is not None:
            self.entity = entity_cell
        espace = _text(_cell(cells, cols.espace))
        if espace is None:
            return
        building = self.current()
        self.after_circulation = False
        qty_raw = _number(_cell(cells, cols.nombre))
        unit = _number(_cell(cells, cols.unit))
        quantity = int(qty_raw) if qty_raw is not None and qty_raw == int(qty_raw) else None
        if unit is not None and quantity is not None and unit > 0:
            self.building_sum += unit * quantity
            self.segment_sum += unit * quantity

        def skip(reason: str) -> None:
            self.result.skipped.append(SkippedRow(building.name, n, espace, reason))

        rule = match_rule(espace, self.rules)
        if rule is None:
            self.result.unmatched.append(Unmatched(building.name, n, espace))
            return
        if rule.type is None:
            skip("exclu par une règle")
            return
        if unit is None or unit <= 0:
            raw = _cell(cells, cols.unit)
            shown = "vide" if raw is None else f"« {raw} »"
            skip(f"surface unitaire non numérique ({shown})")
            return
        if quantity is None or quantity < 1:
            skip(f"nombre invalide (« {_cell(cells, cols.nombre)} »)")
            return
        zone = rule.zone
        if zone is None:
            default = load_taxonomy().get(rule.type).default_macro_zone
            zone = default if default is not None else MacroZone.SERVICES
        entity = self.entity
        name = f"{espace} — {_title_case(entity)}" if entity else espace
        building.lines.append(
            AnnexeLine(
                id=self.next_id(entity),
                name=name[:_NAME_MAX].rstrip(),
                espace=espace,
                entity=entity,
                type=rule.type,
                zone=zone,
                facade=rule.facade,
                quantity=quantity,
                area_m2=unit,
                row=n,
            )
        )


def _fmt(x: Decimal) -> str:
    return f"{float(x):.2f}"


def read_annexe(path: Path, rules: Sequence[AnnexeRule] | None = None) -> AnnexeResult:
    """Read an Annexe "programme physique" workbook.

    Raises :class:`AnnexeError` (French) if the file is unreadable or has no header row.
    Unmatched espaces are collected in ``result.unmatched`` (the caller writes nothing then).
    Buildings without any importable line are dropped with a warning.
    """
    reader = _Reader(load_rules() if rules is None else rules)
    for n, cells in enumerate(_load_sheet_rows(Path(path)), start=1):
        reader.feed(n, cells)
    result = reader.result
    kept = []
    for building in result.buildings:
        if building.lines:
            kept.append(building)
        else:
            result.warnings.append(f"Bâtiment « {building.name} » sans ligne importée : ignoré.")
    result.buildings = kept
    return result


# --------------------------------------------------------------------------- writing


def _write_program_xlsx(program: Program, target: Path) -> None:
    import openpyxl  # type: ignore[import-untyped,unused-ignore]

    from ale.program.template import program_rows, write_template

    write_template(target)
    wb = openpyxl.load_workbook(target)
    ws = wb[SHEET_NAME]
    for row in program_rows(program):
        ws.append(row)
    wb.save(target)


_CSV_HEADER = ("id", "name", "entity", "type", "zone", "facade", "quantity", "area")


def _write_mapping_csv(building: AnnexeBuilding, target: Path) -> None:
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for line in building.lines:
            writer.writerow(
                (
                    line.id,
                    line.name,
                    line.entity,
                    line.type,
                    ZONE_LABELS[line.zone],
                    "Oui" if line.facade else "Non",
                    line.quantity,
                    format(line.area_m2.normalize(), "f"),
                )
            )


def write_outputs(buildings: Sequence[AnnexeBuilding], out_dir: Path) -> list[Path]:
    """Write ``<slug>_programme.xlsx`` and ``<slug>_mapping.csv`` per building."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for building in buildings:
        program = building.program()
        xlsx = out / f"{building.slug}_programme.xlsx"
        _write_program_xlsx(program, xlsx)
        mapping = out / f"{building.slug}_mapping.csv"
        _write_mapping_csv(building, mapping)
        written += [xlsx, mapping]
    return written
