"""Read ``programme.xlsx`` (French headers) into a ``Program`` plus a ``ProgramReport``.

Areas are m², widths metres. Every row and column is checked and every issue is
collected; nothing is raised for bad content (RD 3.1 section 4).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ale.contracts.enums import Bearing, MacroZone, TypeCategory
from ale.contracts.models import Program, RoomSpec
from ale.contracts.taxonomy import Taxonomy, canon, load_taxonomy
from ale.contracts.units import to_decimal
from ale.program.models import Issue, ProgramReport, make_issue

__all__ = [
    "COL_ADJ",
    "COL_AREA",
    "COL_AVOID",
    "COL_FACADE",
    "COL_FLOOR",
    "COL_ID",
    "COL_MIN_WIDTH",
    "COL_NAME",
    "COL_NOTES",
    "COL_QTY",
    "COL_TYPE",
    "COL_ZONE",
    "HEADERS",
    "ORIENTATION_COLUMNS",
    "REQUIRED_HEADERS",
    "SHEET_NAME",
    "ZONE_LABELS",
    "canon_header",
    "issues_from_validation_error",
    "read_program",
    "resolve_type",
]

SHEET_NAME = "Programme"

COL_ID = "ID"
COL_NAME = "Nom"
COL_TYPE = "Type"
COL_AREA = "Surface (m²)"
COL_QTY = "Quantité"
COL_ZONE = "Zone"
COL_FACADE = "Façade"
COL_MIN_WIDTH = "Largeur min (m)"
COL_ADJ = "Adjacent à"
COL_AVOID = "Éviter"
COL_FLOOR = "Niveau"
COL_NOTES = "Remarques"

#: Orientation columns and the bearing each one maps to (``O`` = Ouest → ``Bearing.W``).
ORIENTATION_COLUMNS: tuple[tuple[str, Bearing], ...] = (
    ("Orientation N", Bearing.N),
    ("Orientation E", Bearing.E),
    ("Orientation S", Bearing.S),
    ("Orientation O", Bearing.W),
)

#: The 16 headers of the template, in column order (A-P).
HEADERS: tuple[str, ...] = (
    COL_ID,
    COL_NAME,
    COL_TYPE,
    COL_AREA,
    COL_QTY,
    COL_ZONE,
    COL_FACADE,
    *(name for name, _ in ORIENTATION_COLUMNS),
    COL_MIN_WIDTH,
    COL_ADJ,
    COL_AVOID,
    COL_FLOOR,
    COL_NOTES,
)
REQUIRED_HEADERS: tuple[str, ...] = (COL_ID, COL_NAME, COL_TYPE, COL_AREA)

#: French label of each macro-zone (as written in the template).
ZONE_LABELS: dict[MacroZone, str] = {
    MacroZone.PUBLIC: "Public",
    MacroZone.ADMINISTRATIVE: "Administratif",
    MacroZone.SERVICES: "Services",
}

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$")
_UNIT_SUFFIX_RE = re.compile(r"\s*\(\s*m2?\s*\)\s*$")
_REF_SPLIT_RE = re.compile(r"[,;]")
_NAME_MAX = 120
_AREA_MAX = Decimal(10_000)
_QTY_MAX = 500

_ALLOWED_CATEGORIES = (TypeCategory.ROOM, TypeCategory.VERTICAL)

_TRUE_WORDS = frozenset({"oui", "o", "x", "1", "vrai", "true"})
_FALSE_WORDS = frozenset({"non", "n", "0", "faux", "false"})


def _fold(text: str) -> str:
    """Accent-free, case-folded, whitespace-collapsed form of ``text``."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def canon_header(text: str) -> str:
    """Canonical header: accents, case, extra spaces and a ``(m²)``/``(m)`` suffix ignored."""
    return _UNIT_SUFFIX_RE.sub("", _fold(text)).strip()


_ZONE_WORDS: dict[str, MacroZone] = {
    **{_fold(label): zone for zone, label in ZONE_LABELS.items()},
    **{_fold(zone.name): zone for zone in MacroZone},
}
_TEMPLATE_HEADERS: dict[str, str] = {canon_header(h): h for h in HEADERS}


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value: object) -> Decimal | None:
    """Exact value of a numeric cell (``"12,5"`` accepted), ``None`` if not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            return to_decimal(value)
        except ValueError:  # NaN / infinity
            return None
    if isinstance(value, str):
        text = value.strip()
        if not _NUMBER_RE.match(text):
            return None
        return Decimal(text.replace(",", "."))
    return None


def _id_text(value: object) -> str | None:
    """Text of an id-like cell (integral numbers accepted), ``None`` for other types."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return None


@dataclass(frozen=True)
class _TypeIndex:
    taxonomy: Taxonomy
    keys: frozenset[str]
    by_label: dict[str, str]


_TYPE_INDEX: list[_TypeIndex] = []


def _type_index() -> _TypeIndex:
    if not _TYPE_INDEX:
        tax = load_taxonomy()
        by_label: dict[str, str] = {}
        for t in tax.types:
            by_label.setdefault(canon(t.label_fr), t.key)
        _TYPE_INDEX.append(_TypeIndex(tax, frozenset(tax.keys()), by_label))
    return _TYPE_INDEX[0]


def resolve_type(raw: str) -> tuple[str | None, str | None]:
    """Resolve a ``Type`` cell to ``(key, suggestion)``.

    Accepted: a taxonomy key, a ``label_fr`` (canonical match) or a synonym matched by
    ``normalize_label`` with rule ``exact``. On failure ``key`` is ``None`` and
    ``suggestion`` is the key found by a ``prefix`` match (``None`` if none). The
    category is not checked here.
    """
    idx = _type_index()
    text = raw.strip()
    if text in idx.keys:
        return text, None
    by_label = idx.by_label.get(canon(text))
    if by_label is not None:
        return by_label, None
    match = idx.taxonomy.normalize_label(text)
    if match.rule == "exact":
        return match.key, None
    if match.rule == "prefix":
        return None, match.key
    return None, None


_FIELD_CODES: dict[str, str] = {
    "id": "E_BAD_ID",
    "name": "E_EMPTY_NAME",
    "type": "E_UNKNOWN_TYPE",
    "target_area_m2": "E_AREA",
    "quantity": "E_QUANTITY",
    "macro_zone": "E_ZONE",
    "needs_facade": "E_FACADE",
    "orientation_override": "E_ORIENTATION",
    "min_width_m": "E_MIN_WIDTH",
    "adjacent_to": "E_REF_UNKNOWN",
    "avoid": "E_REF_UNKNOWN",
    "floor": "E_FLOOR",
    "rooms": "E_NO_ROOMS",
}
_FIELD_COLUMNS: dict[str, str] = {
    "id": COL_ID,
    "name": COL_NAME,
    "type": COL_TYPE,
    "target_area_m2": COL_AREA,
    "quantity": COL_QTY,
    "macro_zone": COL_ZONE,
    "needs_facade": COL_FACADE,
    "min_width_m": COL_MIN_WIDTH,
    "adjacent_to": COL_ADJ,
    "avoid": COL_AVOID,
    "floor": COL_FLOOR,
}


def issues_from_validation_error(
    exc: ValidationError, rows: Sequence[int | None] = (), row: int | None = None
) -> list[Issue]:
    """Convert a contract ``ValidationError`` into issues (never re-raised).

    ``loc`` ``(field, ...)`` (a ``RoomSpec``) or ``("rooms", i, field, ...)`` (a
    ``Program``) selects the code; ``rows[i]`` / ``row`` gives the Excel row.
    Cross-field (reference) errors map to ``E_REF_UNKNOWN``.
    """
    out: list[Issue] = []
    for err in exc.errors(include_url=False):
        loc = list(err["loc"])
        at = row
        if len(loc) >= 2 and loc[0] == "rooms" and isinstance(loc[1], int):
            at = rows[loc[1]] if loc[1] < len(rows) else None
            loc = loc[2:]
        name = str(loc[0]) if loc else ""
        code = _FIELD_CODES.get(name, "E_REF_UNKNOWN")
        out.append(
            make_issue(
                code,
                f"Valeur refusée par le contrat : {err['msg']}.",
                row=at,
                column=_FIELD_COLUMNS.get(name),
                value=err.get("input"),
            )
        )
    return out


_Bad = Callable[[str, str, str, object], None]


@dataclass
class _Row:
    row: int
    id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    adjacent: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    ok: bool = True


class _Reader:
    """Stateful row parser: collects issues while converting cells."""

    def __init__(self, columns: dict[str, int]) -> None:
        self.columns = columns
        self.issues: list[Issue] = []

    def add(
        self, code: str, message: str, row: int | None, column: str | None, value: object
    ) -> None:
        self.issues.append(make_issue(code, message, row=row, column=column, value=value))

    # ---------------------------------------------------------------- per column

    def parse_row(self, n: int, cells: tuple[Any, ...]) -> _Row:
        def get(header: str) -> Any:
            col = self.columns.get(header)
            if col is None or col >= len(cells):
                return None
            value = cells[col]
            return None if _is_blank(value) else value

        r = _Row(row=n)

        def bad(code: str, message: str, column: str, value: object) -> None:
            r.ok = False
            self.add(code, message, n, column, value)

        self._id(r, get(COL_ID), bad)
        name = get(COL_NAME)
        if name is None:
            bad("E_EMPTY_NAME", "Le nom est vide.", COL_NAME, name)
        else:
            text = str(name).strip()
            if len(text) > _NAME_MAX:
                bad("E_EMPTY_NAME", f"Le nom dépasse {_NAME_MAX} caractères.", COL_NAME, name)
            r.data["name"] = text
        type_key = self._type(r, get(COL_TYPE), bad)
        self._area(r, get(COL_AREA), bad)
        self._quantity(r, get(COL_QTY), bad)
        self._zone(r, get(COL_ZONE), type_key, bad)
        self._facade(r, get(COL_FACADE), bad)
        self._orientation(r, get, bad)
        self._min_width(r, get(COL_MIN_WIDTH), bad)
        r.adjacent = self._refs(get(COL_ADJ), COL_ADJ, bad)
        r.avoid = self._refs(get(COL_AVOID), COL_AVOID, bad)
        self._floor(r, get(COL_FLOOR), bad)
        return r

    def _id(self, r: _Row, value: Any, bad: _Bad) -> None:
        if value is None:
            bad("E_EMPTY_ID", "L'identifiant est vide.", COL_ID, value)
            return
        text = _id_text(value)
        if text is None or not _ID_RE.match(text):
            bad(
                "E_BAD_ID",
                "L'identifiant doit faire 1 à 32 caractères parmi A-Z, a-z, 0-9, _ et -.",
                COL_ID,
                value,
            )
            return
        r.id = text
        r.data["id"] = text

    def _type(self, r: _Row, value: Any, bad: _Bad) -> str | None:
        if not isinstance(value, str):
            bad("E_UNKNOWN_TYPE", "Le type est vide ou n'est pas un texte.", COL_TYPE, value)
            return None
        key, suggestion = resolve_type(value)
        if key is None:
            message = f"Type inconnu « {value.strip()} »."
            if suggestion is not None:
                sdef = _type_index().taxonomy.get(suggestion)
                message = (
                    f"Type inconnu « {value.strip()} » : vouliez-vous dire "
                    f"« {sdef.label_fr} » ({sdef.key}) ?"
                )
            bad("E_UNKNOWN_TYPE", message, COL_TYPE, value)
            return None
        tdef = _type_index().taxonomy.get(key)
        if tdef.category not in _ALLOWED_CATEGORIES:
            bad(
                "E_FORBIDDEN_TYPE",
                f"Le type « {tdef.label_fr} » ({key}) ne peut pas figurer au programme "
                "(circulation ou type spécial).",
                COL_TYPE,
                value,
            )
            return None
        r.data["type"] = key
        return key

    def _area(self, r: _Row, value: Any, bad: _Bad) -> None:
        d = _number(value)
        if d is None or not Decimal(0) < d <= _AREA_MAX:
            bad(
                "E_AREA",
                "La surface doit être un nombre > 0 et ≤ 10 000 m².",
                COL_AREA,
                value,
            )
            return
        r.data["target_area_m2"] = float(d)

    def _quantity(self, r: _Row, value: Any, bad: _Bad) -> None:
        if value is None:
            r.data["quantity"] = 1
            return
        d = _number(value)
        if d is None or d != d.to_integral_value() or not 1 <= d <= _QTY_MAX:
            bad("E_QUANTITY", "La quantité doit être un entier de 1 à 500.", COL_QTY, value)
            return
        r.data["quantity"] = int(d)

    def _zone(self, r: _Row, value: Any, type_key: str | None, bad: _Bad) -> None:
        if value is None:
            if type_key is None:
                return
            zone = _type_index().taxonomy.get(type_key).default_macro_zone
            if zone is None:  # pragma: no cover - every ROOM/VERTICAL type has one
                bad("E_ZONE", "La zone est obligatoire pour ce type.", COL_ZONE, value)
                return
            r.data["macro_zone"] = zone
            self.add(
                "W_ZONE_DEFAULTED",
                f"Zone vide : zone par défaut du type retenue ({ZONE_LABELS[zone]}).",
                r.row,
                COL_ZONE,
                value,
            )
            return
        zone = _ZONE_WORDS.get(_fold(value)) if isinstance(value, str) else None
        if zone is None:
            bad(
                "E_ZONE",
                "La zone doit être Public, Administratif ou Services.",
                COL_ZONE,
                value,
            )
            return
        r.data["macro_zone"] = zone

    def _facade(self, r: _Row, value: Any, bad: _Bad) -> None:
        if value is None:
            r.data["needs_facade"] = False
            return
        if isinstance(value, bool):
            r.data["needs_facade"] = value
            return
        if isinstance(value, int | float):
            word = "1" if value == 1 else "0" if value == 0 else None
        elif isinstance(value, str):
            word = _fold(value)
        else:
            word = None
        if word in _TRUE_WORDS:
            r.data["needs_facade"] = True
        elif word in _FALSE_WORDS:
            r.data["needs_facade"] = False
        else:
            bad(
                "E_FACADE",
                "La façade doit valoir Oui ou Non (O/N, X, 1/0, Vrai/Faux).",
                COL_FACADE,
                value,
            )

    def _orientation(self, r: _Row, get: Callable[[str], Any], bad: _Bad) -> None:
        values = [(header, bearing, get(header)) for header, bearing in ORIENTATION_COLUMNS]
        if all(v is None for _, _, v in values):
            r.data["orientation_override"] = None
            return
        out: dict[Bearing, float] = {}
        for header, bearing, value in values:
            if value is None:
                out[bearing] = 0.0
                continue
            d = _number(value)
            if d is None or not Decimal(-1) <= d <= Decimal(1):
                bad(
                    "E_ORIENTATION",
                    "L'orientation doit être un nombre entre -1 et 1.",
                    header,
                    value,
                )
                continue
            out[bearing] = float(d)
        r.data["orientation_override"] = out

    def _min_width(self, r: _Row, value: Any, bad: _Bad) -> None:
        if value is None:
            r.data["min_width_m"] = None
            return
        d = _number(value)
        if d is None or d <= 0:
            bad(
                "E_MIN_WIDTH",
                "La largeur minimale doit être un nombre > 0 m.",
                COL_MIN_WIDTH,
                value,
            )
            return
        r.data["min_width_m"] = float(d)

    def _refs(self, value: Any, column: str, bad: _Bad) -> tuple[str, ...]:
        if value is None:
            return ()
        text = _id_text(value)
        if text is None:
            bad(
                "E_REF_UNKNOWN",
                "Les références doivent être des identifiants séparés par , ou ;.",
                column,
                value,
            )
            return ()
        out: list[str] = []
        for token in _REF_SPLIT_RE.split(text):
            ref = token.strip()
            if ref and ref not in out:
                out.append(ref)
        return tuple(out)

    def _floor(self, r: _Row, value: Any, bad: _Bad) -> None:
        if value is None:
            r.data["floor"] = 0
            return
        d = _number(value)
        if d is None or d != 0:
            bad("E_FLOOR", "Seul le niveau 0 est accepté en v1.", COL_FLOOR, value)
            return
        r.data["floor"] = 0

    # ---------------------------------------------------------------- cross-row

    def check_references(self, rows: list[_Row], known: set[str]) -> None:
        by_id = {r.id: r for r in rows if r.id is not None}
        for r in rows:
            for column, refs in ((COL_ADJ, r.adjacent), (COL_AVOID, r.avoid)):
                for ref in refs:
                    if ref == r.id:
                        r.ok = False
                        self.add(
                            "E_SELF_REF",
                            f"La pièce « {ref} » se référence elle-même.",
                            r.row,
                            column,
                            ref,
                        )
                    elif ref not in known:
                        r.ok = False
                        self.add(
                            "E_REF_UNKNOWN",
                            f"Identifiant référencé inconnu « {ref} ».",
                            r.row,
                            column,
                            ref,
                        )
            for ref in r.adjacent:
                if ref == r.id or ref not in known:
                    continue
                other = by_id.get(ref)
                if ref in r.avoid:
                    message = f"« {ref} » figure à la fois dans Adjacent à et Éviter."
                elif other is not None and r.id in other.avoid:
                    message = f"« {r.id} » exige « {ref} », mais « {ref} » évite « {r.id} »."
                else:
                    continue
                r.ok = False
                self.add("E_REQ_AVOID_CONFLICT", message, r.row, COL_ADJ, ref)


def _load_rows(path: Path, issues: list[Issue]) -> tuple[str | None, list[tuple[Any, ...]]] | None:
    import openpyxl  # type: ignore[import-untyped,unused-ignore]

    try:
        wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    except Exception as exc:  # any openpyxl / zip / OS failure
        issues.append(
            make_issue(
                "E_FILE_UNREADABLE",
                f"Classeur Excel illisible : {type(exc).__name__}: {exc}.",
                value=str(path),
            )
        )
        return None
    try:
        names: list[str] = list(wb.sheetnames)
        if SHEET_NAME in names:
            name = SHEET_NAME
        else:
            name = names[0]
            issues.append(
                make_issue(
                    "W_SHEET_NAME",
                    f"Pas de feuille « {SHEET_NAME} » : la première feuille est lue.",
                    value=name,
                )
            )
        ws = wb[name]
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    return name, rows


def _header_columns(header: tuple[Any, ...], issues: list[Issue]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for col, cell in enumerate(header):
        if _is_blank(cell):
            continue
        text = str(cell).strip()
        known = _TEMPLATE_HEADERS.get(canon_header(text))
        if known is None or known in columns:
            why = "inconnue" if known is None else "en double"
            issues.append(
                make_issue(
                    "W_UNKNOWN_COLUMN",
                    f"Colonne {why} « {text} » ignorée.",
                    row=1,
                    column=text,
                    value=cell,
                )
            )
            continue
        columns[known] = col
    for required in REQUIRED_HEADERS:
        if required not in columns:
            issues.append(
                make_issue(
                    "E_MISSING_COLUMN",
                    f"Colonne obligatoire « {required} » absente.",
                    row=1,
                    column=required,
                )
            )
    return columns


def _sort_key(issue: Issue) -> int:
    return 0 if issue.row is None else issue.row


def read_program(path: Path) -> tuple[Program | None, ProgramReport]:
    """Read ``programme.xlsx``; the ``Program`` is ``None`` iff the report has errors."""
    issues: list[Issue] = []
    loaded = _load_rows(path, issues)
    if loaded is None:
        return None, ProgramReport(issues=tuple(issues))
    sheet, rows = loaded
    header = rows[0] if rows else ()
    columns = _header_columns(header, issues)
    if any(i.code == "E_MISSING_COLUMN" for i in issues):
        return None, ProgramReport(sheet=sheet, issues=tuple(issues))

    reader = _Reader(columns)
    parsed: list[_Row] = []
    seen: dict[str, int] = {}
    for n, cells in enumerate(rows[1:], start=2):
        if all(_is_blank(c) for c in cells):
            continue
        first = cells[columns[COL_ID]] if columns[COL_ID] < len(cells) else None
        if isinstance(first, str) and first.strip().startswith("#"):
            continue
        r = reader.parse_row(n, cells)
        if r.id is not None:
            if r.id in seen:
                r.ok = False
                reader.add(
                    "E_DUP_ID",
                    f"Identifiant « {r.id} » déjà utilisé ligne {seen[r.id]}.",
                    n,
                    COL_ID,
                    r.id,
                )
            else:
                seen[r.id] = n
        parsed.append(r)
    reader.check_references(parsed, set(seen))
    if not parsed:
        reader.add("E_NO_ROOMS", "Le programme ne contient aucune pièce.", None, None, None)

    all_issues = issues + sorted(reader.issues, key=_sort_key)
    types = tuple(sorted({r.data["type"] for r in parsed if "type" in r.data}))
    row_map = {r.id: r.row for r in parsed if r.id is not None and seen.get(r.id) == r.row}
    program: Program | None = None
    if not any(i.severity == "error" for i in all_issues):
        program, contract_issues = _build(parsed)
        all_issues.extend(contract_issues)
    report = ProgramReport(sheet=sheet, issues=tuple(all_issues), rows=row_map, types=types)
    return program, report


def _build(parsed: list[_Row]) -> tuple[Program | None, list[Issue]]:
    specs: list[RoomSpec] = []
    issues: list[Issue] = []
    for r in parsed:
        data = dict(r.data, adjacent_to=r.adjacent, avoid=r.avoid)
        try:
            specs.append(RoomSpec.model_validate(data))
        except ValidationError as exc:
            issues.extend(issues_from_validation_error(exc, row=r.row))
    if issues:
        return None, issues
    try:
        return Program(rooms=tuple(specs)), []
    except ValidationError as exc:  # pragma: no cover - cross-row checks run before
        return None, issues_from_validation_error(exc, rows=[r.row for r in parsed])
