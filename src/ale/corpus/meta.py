"""``plans_meta.csv`` parsing (Ticket 1.1 RD section 5).

UTF-8 (a BOM is accepted), ``,`` or ``;`` separator auto-detected from the header line.
Columns: ``filename,page,scale_1_to,units,building_type,floor,exclude``; only
``filename`` is required. Bad rows become warnings, never errors.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["COLUMNS", "MetaParse", "MetaRow", "parse_meta", "parse_meta_text"]

COLUMNS = ("filename", "page", "scale_1_to", "units", "building_type", "floor", "exclude")
TRUTHY = frozenset({"1", "oui", "yes", "x", "true", "y", "o", "vrai"})
FALSY = frozenset({"", "0", "non", "no", "false", "n", "faux"})
_TEXT_FIELDS = ("units", "building_type", "floor")


@dataclass(frozen=True)
class MetaRow:
    line: int
    filename: str
    #: Page index (0-based, as ``units.page``); None = the whole file.
    page: int | None
    exclude: bool
    #: Fields to store in ``files.meta_json`` (non-empty only).
    fields: dict[str, Any]


@dataclass
class MetaParse:
    rows: list[MetaRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _detect_delimiter(header_line: str) -> str:
    return ";" if header_line.count(";") > header_line.count(",") else ","


def _number(text: str) -> float | int | None:
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return int(value) if value.is_integer() else value


def _parse_row(line: int, record: dict[str, str], warnings: list[str]) -> MetaRow | None:
    where = f"plans_meta.csv line {line}"
    filename = record.get("filename", "").strip()
    if not filename:
        warnings.append(f"{where}: empty filename, row ignored")
        return None
    page: int | None = None
    page_text = record.get("page", "").strip()
    if page_text:
        if not page_text.isdigit():
            warnings.append(
                f"{where}: page {page_text!r} is not a non-negative integer, row ignored"
            )
            return None
        page = int(page_text)
    exclude_text = record.get("exclude", "").strip().lower()
    if exclude_text not in TRUTHY and exclude_text not in FALSY:
        warnings.append(f"{where}: exclude {exclude_text!r} not understood, treated as no")
    fields: dict[str, Any] = {}
    scale_text = record.get("scale_1_to", "").strip()
    if scale_text:
        scale = _number(scale_text)
        if scale is None or scale <= 0:
            warnings.append(f"{where}: scale_1_to {scale_text!r} is not a positive number, ignored")
        else:
            fields["scale_1_to"] = scale
    for name in _TEXT_FIELDS:
        value = record.get(name, "").strip()
        if value:
            fields[name] = value
    return MetaRow(line, filename, page, exclude_text in TRUTHY, fields)


def parse_meta_text(text: str) -> MetaParse:
    """Parse the CSV text (BOM already removed or not)."""
    result = MetaParse()
    text = text.removeprefix("﻿")
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    if not first_line:
        result.warnings.append("plans_meta.csv: empty file")
        return result
    reader = csv.reader(io.StringIO(text), delimiter=_detect_delimiter(first_line))
    header: list[str] | None = None
    for row in reader:
        line = reader.line_num
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = [cell.strip().lower() for cell in row]
            unknown = [h for h in header if h not in COLUMNS]
            if unknown:
                result.warnings.append(
                    f"plans_meta.csv: unknown column(s) ignored: {', '.join(unknown)}"
                )
            if "filename" not in header:
                result.warnings.append("plans_meta.csv: missing column 'filename', file ignored")
                return result
            continue
        if len(row) > len(header):
            result.warnings.append(f"plans_meta.csv line {line}: too many cells, row ignored")
            continue
        record = {name: cell for name, cell in zip(header, row, strict=False)}
        parsed = _parse_row(line, record, result.warnings)
        if parsed is not None:
            result.rows.append(parsed)
    return result


def parse_meta(path: Path) -> MetaParse:
    """Read and parse ``path``; an unreadable file is a single warning."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return MetaParse(warnings=[f"plans_meta.csv: not valid UTF-8 ({exc.reason}), ignored"])
    except OSError as exc:
        return MetaParse(warnings=[f"plans_meta.csv: cannot read ({exc.strerror or exc}), ignored"])
    return parse_meta_text(text)
