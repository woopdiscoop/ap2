"""``run_extract`` / ``run_layers``: the CAD reader wired to the corpus (Ticket 1.2c).

``run_layers`` collects the model-space layer names of every DXF unit (and of every DWG
unit whose conversion succeeds or is cached), merges them into ``layer_map.yaml`` (user
entries win) and returns what changed.

``run_extract`` reads the selected units and writes one
``extracted/<sha256>/<page>/<plan_index>/plan.json`` per plan
(``canonical_json(PlanGeometry)``, atomic rewrite, unchanged bytes are not rewritten).
CAD, vector/scanned PDF and raster units share scale, text labelling and review flags.
A failing unit never aborts the run.

Sources are read from the input folders recorded in ``corpus.sqlite``; nothing is ever
written there (DWG conversion works on a temporary copy, output goes to ``cache/dxf``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ale.cad import (
    LayerMap,
    convert_dwg,
    load_layer_map,
    propose_layer_map,
    read_cad,
    save_layer_map,
)
from ale.contracts.enums import FileStatus, SourceKind
from ale.contracts.models import PlanGeometry
from ale.contracts.serialization import canonical_json
from ale.corpus.db import CorpusDbError, add_event, connect, migrate, utc_now
from ale.join import resolve_scale, review_flags
from ale.labels import VlmCache, label_plan
from ale.pdfread import read_pdf_page
from ale.raster import rasterize_pdf_page, read_raster
from ale.workspace import CORPUS_FILENAME, LAYER_MAP_FILENAME, Workspace, WorkspaceError

__all__ = [
    "KIND_FILTERS",
    "NO_PLAN_REASON",
    "ExtractReport",
    "LayerRow",
    "LayersReport",
    "model_space_layers",
    "plan_path",
    "run_extract",
    "run_layers",
]

log = logging.getLogger(__name__)

NO_PLAN_REASON = "no plan found"
#: ``--kind`` value → unit kinds (``units.kind``) it selects.
KIND_FILTERS: dict[str, tuple[str, ...]] = {
    "dwg": (SourceKind.DWG.value,),
    "dxf": (SourceKind.DXF.value,),
    "pdf": (SourceKind.PDF_VECTOR.value, SourceKind.PDF_SCANNED.value),
    "raster": (SourceKind.RASTER.value,),
}
_CAD_KINDS = (SourceKind.DXF.value, SourceKind.DWG.value)
_MAX_BLOCK_DEPTH = 16


# ---------------------------------------------------------------------- shared helpers


@dataclass(frozen=True)
class _Unit:
    sha256: str
    page: int
    kind: str
    status: str
    meta: dict[str, Any]


def _open_corpus(ws: Workspace) -> sqlite3.Connection:
    try:
        conn = connect(ws.path(CORPUS_FILENAME))
    except sqlite3.Error as exc:  # pragma: no cover - open_workspace checked the file
        raise WorkspaceError(f"{CORPUS_FILENAME}: cannot be opened ({exc})") from exc
    try:
        migrate(conn)
    except (CorpusDbError, sqlite3.Error) as exc:
        conn.close()
        raise WorkspaceError(f"{CORPUS_FILENAME}: {exc}") from exc
    return conn


def _source_path(conn: sqlite3.Connection, sha: str) -> tuple[Path | None, str]:
    """First recorded path of ``sha`` that still exists, and a name for messages."""
    rows = conn.execute(
        "SELECT i.root, p.rel_path FROM file_paths p JOIN inputs i ON i.id = p.input_id "
        "WHERE p.sha256 = ? ORDER BY p.input_id, p.rel_path",
        (sha,),
    ).fetchall()
    for root, rel in rows:
        path = Path(str(root)).joinpath(*str(rel).split("/"))
        if path.is_file():
            return path, str(rel)
    name = str(rows[0][1]) if rows else sha[:12]
    return None, name


def _units_override(meta: Mapping[str, Any], page: int) -> str | None:
    page_meta = meta.get("pages", {}).get(str(page), {})
    value = page_meta.get("units", meta.get("units"))
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def _layer_map(ws: Workspace) -> LayerMap:
    path = ws.path(LAYER_MAP_FILENAME)
    if not path.is_file():
        return LayerMap()
    try:
        return load_layer_map(path)
    except Exception as exc:  # YAML or validation error: the user must fix the file
        raise WorkspaceError(f"{LAYER_MAP_FILENAME}: invalid ({exc})") from exc


def _dxf_for(
    ws: Workspace, unit: _Unit, source: Path, environ: Mapping[str, str] | None
) -> tuple[Path | None, str, str]:
    """(DXF path or None, convert status, message) for a DXF or DWG unit."""
    if unit.kind == SourceKind.DXF.value:
        return source, "OK", ""
    result = convert_dwg(
        source, ws.path("cache", "dxf"), ws.config, workspace_root=ws.root, environ=environ
    )
    return result.dxf_path if result.ok else None, result.status, result.message


# ---------------------------------------------------------------------- layers


def _open_dxf(path: Path) -> Any:
    from ezdxf import recover
    from ezdxf.filemanagement import readfile

    try:
        return readfile(path)
    except OSError:
        raise
    except Exception:
        doc, _auditor = recover.readfile(path)
        return doc


def _block_layers(
    doc: Any, name: str, parent: str, depth: int, seen: set[tuple[str, str]]
) -> Iterator[str]:
    if depth > _MAX_BLOCK_DEPTH or (name, parent) in seen:
        return
    seen.add((name, parent))
    block = doc.blocks.get(name)
    if block is None or block.block.is_xref or block.block.is_xref_overlay:
        return
    yield from _entity_layers(doc, block, parent, depth, seen)


def _entity_layers(
    doc: Any, entities: Iterable[Any], parent: str | None, depth: int, seen: set[tuple[str, str]]
) -> Iterator[str]:
    for e in entities:
        layer = str(e.dxf.get("layer", "0"))
        if parent is not None and layer == "0":
            layer = parent
        yield layer
        if e.dxftype() == "INSERT":
            for attrib in getattr(e, "attribs", ()):
                a_layer = str(attrib.dxf.get("layer", "0"))
                yield layer if a_layer == "0" else a_layer
            yield from _block_layers(doc, str(e.dxf.name), layer, depth + 1, seen)


def model_space_layers(path: Path) -> tuple[str, ...]:
    """Sorted names of the layers used in model space (block contents included, entities
    on layer ``0`` inside a block take the layer of the INSERT). Raises on unreadable files.
    """
    doc = _open_dxf(path)
    return tuple(sorted(set(_entity_layers(doc, doc.modelspace(), None, 0, set()))))


@dataclass(frozen=True)
class LayerRow:
    layer: str
    role: str
    files: int
    new: bool


@dataclass
class LayersReport:
    """What ``ale layers`` did."""

    files_read: int = 0
    rows: list[LayerRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    saved: bool = False

    @property
    def new_count(self) -> int:
        return sum(1 for r in self.rows if r.new)


def run_layers(ws: Workspace, *, environ: Mapping[str, str] | None = None) -> LayersReport:
    """Propose roles for the CAD layers of the corpus and save ``layer_map.yaml``."""
    report = LayersReport()
    existing = _layer_map(ws)
    usage: Counter[str] = Counter()
    with closing(_open_corpus(ws)) as conn:
        rows = conn.execute(
            "SELECT DISTINCT sha256, kind FROM units WHERE kind IN (?, ?) AND status != ? "
            "ORDER BY sha256",
            (*_CAD_KINDS, FileStatus.EXCLUDED.value),
        ).fetchall()
        sources = [(str(sha), str(kind), *_source_path(conn, str(sha))) for sha, kind in rows]
    for sha, kind, source, name in sources:
        if source is None:
            report.warnings.append(f"{name}: source file not found, skipped")
            continue
        unit = _Unit(sha, 0, kind, "", {})
        dxf, status, message = _dxf_for(ws, unit, source, environ)
        if dxf is None:
            report.warnings.append(f"{name}: DWG not converted ({status}: {message}), skipped")
            continue
        try:
            names = model_space_layers(dxf)
        except Exception as exc:
            report.warnings.append(f"{name}: cannot read layers ({type(exc).__name__}: {exc})")
            continue
        report.files_read += 1
        usage.update(names)
    for warning in report.warnings:
        log.warning("%s", warning, extra={"event": "corpus.layers.skipped"})
    if not usage:
        return report
    merged = propose_layer_map(sorted(usage), existing)
    save_layer_map(merged, ws.path(LAYER_MAP_FILENAME))
    report.saved = True
    report.rows = [
        LayerRow(layer, str(merged.role(layer)), usage[layer], layer not in existing.layers)
        for layer in sorted(usage)
    ]
    log.info(
        "layer_map.yaml: %d layers from %d files, %d new",
        len(report.rows),
        report.files_read,
        report.new_count,
        extra={"event": "corpus.layers"},
    )
    return report


# ---------------------------------------------------------------------- extract


@dataclass
class ExtractReport:
    """What ``ale extract`` did."""

    selected: int = 0
    extracted: int = 0
    failed: int = 0
    needs_tool: int = 0
    not_implemented: int = 0
    excluded: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    plans: int = 0
    files_written: int = 0
    #: Layers proposed in memory because ``layer_map.yaml`` had none (None: map used).
    proposed_layers: int | None = None
    #: (name, reason) of the units that failed or still need a tool.
    problems: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "extracted": self.extracted,
            "failed": self.failed,
            "needs_tool": self.needs_tool,
            "not_implemented": self.not_implemented,
            "excluded": self.excluded,
            "by_kind": dict(sorted(self.by_kind.items())),
            "plans": self.plans,
            "files_written": self.files_written,
            "proposed_layers": self.proposed_layers,
            "problems": [list(p) for p in self.problems],
        }


def plan_path(ws: Workspace, sha: str, page: int, plan_index: int) -> Path:
    """``extracted/<sha256>/<page>/<plan_index>/plan.json`` of the workspace."""
    return ws.path("extracted", sha, str(page), str(plan_index), "plan.json")


def _write_atomic(path: Path, data: bytes) -> bool:
    """Write ``data`` (temp file + replace); False when the file already holds it."""
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        Path(tmp).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise
    return True


def _remove_stale(ws: Workspace, sha: str, page: int, keep: int) -> None:
    """Remove ``<plan_index>`` folders ≥ ``keep`` left by an earlier extraction (the page
    folder exists: at least one plan was just written)."""
    for child in ws.path("extracted", sha, str(page)).iterdir():
        if child.is_dir() and child.name.isdigit() and int(child.name) >= keep:
            shutil.rmtree(child, ignore_errors=True)


def _select(conn: sqlite3.Connection, only_new: bool, kind: str | None) -> list[_Unit]:
    statuses = (
        (FileStatus.NEW.value,) if only_new else (FileStatus.NEW.value, FileStatus.FAILED.value)
    )
    where = f"u.status IN ({', '.join('?' * len(statuses))})"
    params: list[str] = list(statuses)
    if not only_new:  # retry DWG units waiting for a converter
        where = f"({where} OR (u.status = ? AND u.kind = ?))"
        params += [FileStatus.NEEDS_TOOL.value, SourceKind.DWG.value]
    sql = (
        "SELECT u.sha256, u.page, u.kind, u.status, f.meta_json FROM units u "
        f"JOIN files f ON f.sha256 = u.sha256 WHERE {where}"
    )
    if kind is not None:
        kinds = KIND_FILTERS[kind]
        sql += f" AND u.kind IN ({', '.join('?' * len(kinds))})"
        params.extend(kinds)
    sql += " ORDER BY u.sha256, u.page"
    return [
        _Unit(str(sha), int(page), str(k), str(st), json.loads(meta) if meta else {})
        for sha, page, k, st, meta in conn.execute(sql, params).fetchall()
    ]


def _set_status(
    conn: sqlite3.Connection, unit: _Unit, status: FileStatus, reason: str | None
) -> None:
    conn.execute(
        "UPDATE units SET status = ?, reason = ?, updated_at = ? WHERE sha256 = ? AND page = ?",
        (status.value, reason, utc_now(), unit.sha256, unit.page),
    )


def _page_meta(unit: _Unit) -> dict[str, Any]:
    """Page fields override file fields; unspecified fields inherit from the file."""
    meta = {k: v for k, v in unit.meta.items() if k != "pages"}
    meta.update(unit.meta.get("pages", {}).get(str(unit.page), {}))
    return meta


def _exclude(
    conn: sqlite3.Connection,
    unit: _Unit,
    name: str,
    score: float,
    report: ExtractReport,
    warnings: tuple[str, ...],
) -> None:
    reason = f"not a plan (score {score:.2f})"
    _set_status(conn, unit, FileStatus.EXCLUDED, reason)
    conn.execute("DELETE FROM review_flags WHERE sha256 = ? AND page = ?", (unit.sha256, unit.page))
    add_event(
        conn,
        "extract_excluded",
        unit.sha256,
        unit.page,
        {"rel_path": name, "reason": reason, "warnings": list(warnings)},
    )
    report.excluded += 1
    report.problems.append((name, reason))


def _extract_unit(
    ws: Workspace,
    conn: sqlite3.Connection,
    unit: _Unit,
    layer_map: LayerMap,
    report: ExtractReport,
    environ: Mapping[str, str] | None,
) -> None:
    source, name = _source_path(conn, unit.sha256)
    if source is None:
        raise FileNotFoundError(f"source file not found: {name}")
    meta = _page_meta(unit)
    plans: tuple[PlanGeometry, ...]
    warnings: tuple[str, ...]
    if unit.kind in _CAD_KINDS:
        dxf, status, message = _dxf_for(ws, unit, source, environ)
        if dxf is None:
            if status == "NEEDS_TOOL":
                report.needs_tool += 1
                if unit.status == FileStatus.NEEDS_TOOL.value:
                    return
                _set_status(conn, unit, FileStatus.NEEDS_TOOL, message)
                report.problems.append((name, message))
                log.warning("%s: %s", name, message, extra={"event": "corpus.extract.needs_tool"})
                return
            _fail(conn, unit, name, f"DWG conversion failed: {message}", report)
            return
        cad = read_cad(
            dxf,
            source_sha256=unit.sha256,
            layer_map=layer_map,
            config=ws.config,
            units_override=_units_override(unit.meta, unit.page),
            source_kind=SourceKind(unit.kind),
        )
        plans, warnings = cad.plans, cad.warnings
    elif unit.kind == SourceKind.PDF_VECTOR.value:
        pdf = read_pdf_page(source, unit.page, source_sha256=unit.sha256, config=ws.config)
        if not pdf.is_plan_likely:
            _exclude(conn, unit, name, pdf.plan_score, report, pdf.warnings)
            return
        plans, warnings = pdf.plans, pdf.warnings
    else:
        if unit.kind not in (SourceKind.PDF_SCANNED.value, SourceKind.RASTER.value):
            raise ValueError(f"unsupported source kind {unit.kind}")
        if unit.kind == SourceKind.PDF_SCANNED.value:
            image = rasterize_pdf_page(
                source, unit.page, dpi=meta.get("dpi", ws.config.extract.raster_dpi)
            )
            raster = read_raster(
                image,
                source_sha256=unit.sha256,
                page=unit.page,
                source_kind=SourceKind.PDF_SCANNED,
                config=ws.config,
            )
        else:
            raster = read_raster(
                source, source_sha256=unit.sha256, page=unit.page, config=ws.config
            )
        if raster.plan_score < 0.3:
            _exclude(conn, unit, name, raster.plan_score, report, raster.warnings)
            return
        plans, warnings = raster.plans, raster.warnings
    if not plans:
        _fail(conn, unit, name, NO_PLAN_REASON, report, warnings=warnings)
        return
    processed = []
    for plan in plans:
        scaled = resolve_scale(plan, meta=meta, config=ws.config)
        labelled = label_plan(
            scaled, image=None, provider=None, cache=VlmCache.for_workspace(ws), config=ws.config
        )
        processed.append(
            labelled.plan.model_copy(
                update={
                    "warnings": tuple(dict.fromkeys((*labelled.plan.warnings, *labelled.warnings)))
                }
            )
        )
    conn.execute("DELETE FROM review_flags WHERE sha256 = ? AND page = ?", (unit.sha256, unit.page))

    written = 0
    for plan in processed:
        if _write_atomic(
            plan_path(ws, unit.sha256, unit.page, plan.plan_index), canonical_json(plan)
        ):
            written += 1
        conn.executemany(
            "INSERT INTO review_flags (sha256, page, plan_index, flag) VALUES (?, ?, ?, ?)",
            [
                (unit.sha256, unit.page, plan.plan_index, flag)
                for flag in review_flags(plan, ws.config)
            ],
        )
    _remove_stale(ws, unit.sha256, unit.page, len(processed))
    _set_status(conn, unit, FileStatus.EXTRACTED, None)
    detail = {
        "rel_path": name,
        "plans": len(processed),
        "source_kind": unit.kind,
        "warnings": list(warnings),
    }
    add_event(conn, "extracted", unit.sha256, unit.page, detail)
    report.extracted += 1
    report.by_kind[unit.kind] = report.by_kind.get(unit.kind, 0) + 1
    report.plans += len(processed)
    report.files_written += written
    log.info(
        "%s: %d plan(s) extracted",
        name,
        len(processed),
        extra={"event": "corpus.extracted", "sha256": unit.sha256, "plans": len(processed)},
    )


def _fail(
    conn: sqlite3.Connection,
    unit: _Unit,
    name: str,
    reason: str,
    report: ExtractReport,
    warnings: Iterable[str] = (),
) -> None:
    _set_status(conn, unit, FileStatus.FAILED, reason)
    detail = {"rel_path": name, "reason": reason, "warnings": list(warnings)}
    add_event(conn, "extract_failed", unit.sha256, unit.page, detail)
    report.failed += 1
    report.problems.append((name, reason))
    log.warning("%s: extraction failed: %s", name, reason, extra={"event": "corpus.extract_failed"})


def _proposed_map(
    ws: Workspace,
    conn: sqlite3.Connection,
    units: Iterable[_Unit],
    environ: Mapping[str, str] | None,
) -> LayerMap:
    """In-memory proposal over the layers of the selected CAD units (never saved)."""
    names: set[str] = set()
    for unit in units:
        if unit.kind not in _CAD_KINDS:
            continue
        source = _source_path(conn, unit.sha256)[0]
        if source is None:
            continue
        dxf = _dxf_for(ws, unit, source, environ)[0]
        if dxf is None:
            continue
        with contextlib.suppress(Exception):  # the extraction reports unreadable files
            names.update(model_space_layers(dxf))
    return propose_layer_map(sorted(names))


def run_extract(
    ws: Workspace,
    *,
    only_new: bool = False,
    kind: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ExtractReport:
    """Extract the selected units (``kind``: a key of :data:`KIND_FILTERS` or None).

    Selection: status NEW (``only_new``) or NEW, FAILED and DWG units in NEEDS_TOOL
    (default, retry). An empty ``layer_map.yaml`` is replaced, for this run only, by a
    proposal over the selected units' layers. Raises
    :class:`WorkspaceError` only when the corpus or ``layer_map.yaml`` cannot be used.
    """
    if kind is not None and kind not in KIND_FILTERS:
        raise ValueError(f"unknown kind {kind!r}")
    report = ExtractReport()
    layer_map = _layer_map(ws)
    with closing(_open_corpus(ws)) as conn:
        units = _select(conn, only_new, kind)
        report.selected = len(units)
        if not layer_map.layers and any(u.kind in _CAD_KINDS for u in units):
            layer_map = _proposed_map(ws, conn, units, environ)
            report.proposed_layers = len(layer_map.layers)
            log.warning(
                "layer_map.yaml has no layers: %d roles proposed for this run only",
                report.proposed_layers,
                extra={"event": "corpus.extract.proposed_layer_map"},
            )
        for unit in units:
            try:
                _extract_unit(ws, conn, unit, layer_map, report, environ)
            except Exception as exc:  # one unit must never abort the run
                name = _source_path(conn, unit.sha256)[1]
                _fail(conn, unit, name, f"{type(exc).__name__}: {exc}", report)
            conn.commit()
    log.info(
        "extract: %d selected, %d extracted, %d failed",
        report.selected,
        report.extracted,
        report.failed,
        extra={
            "event": "corpus.extract",
            **{k: v for k, v in report.to_dict().items() if k != "problems"},
        },
    )
    return report
