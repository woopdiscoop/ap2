"""Build the rulebook from extracted plans (Ticket 2.2): :func:`build_rulebook`, :func:`run_build`.

``build_rulebook`` is pure (inputs → ``BuildResult``); ``run_build`` loads every
``extracted/**/plan.json`` of a workspace whose unit is EXTRACTED and not excluded, runs
:func:`~ale.mining.extract_topology` (plans with an unknown scale are skipped and
reported), builds, and writes ``rulebook/rulebook.yaml``, ``rulebook/report.md`` and
``rulebook/rulebook.sqlite`` (tables ``plans``, ``rooms``, ``contacts``: the inputs, for
audit).

``version = "mined-<12 hex>"`` where the hex digits start the SHA-256 of the inputs (plans
sorted by key, seed, rulebook / shape settings, ``min_support``); there is no date in the
rulebook, so identical inputs give a byte-identical ``rulebook.yaml`` on any day. The build
date (UTC) appears only in ``report.md``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import shapely
from pydantic import ValidationError

from ale.contracts.config import AleConfig
from ale.contracts.enums import Fidelity, FileStatus
from ale.contracts.models import PlanGeometry, Rulebook
from ale.contracts.serialization import canonical_json, dump_yaml, load_yaml
from ale.mining import PlanTopology, extract_topology
from ale.rulebook.blend import blend_rulebook
from ale.rulebook.report import ReportInputs, render_report
from ale.rulebook.stats import (
    BEARINGS,
    PlanInput,
    adjacency_stats,
    core_offset_stats,
    orientation_stats,
    room_aspect,
    room_facades,
    shape_stats,
)
from ale.workspace import CORPUS_FILENAME, Workspace

__all__ = [
    "REASON_BAD_PLAN",
    "REASON_NO_GEOMETRY",
    "REASON_NO_SCALE",
    "BuildResult",
    "RunResult",
    "SeedError",
    "build_rulebook",
    "load_seed",
    "run_build",
]

REASON_NO_SCALE = "échelle inconnue"
REASON_NO_GEOMETRY = "géométrie absente"
REASON_BAD_PLAN = "plan.json illisible"

PlanKey = tuple[str, int, int]


@dataclass(frozen=True)
class BuildResult:
    rulebook: Rulebook
    report_md: str


@dataclass(frozen=True)
class RunResult:
    result: BuildResult
    used: int
    skipped: tuple[tuple[str, str], ...]
    files: tuple[Path, ...]


class SeedError(Exception):
    """The seed rulebook cannot be read or is invalid."""


def _label(key: PlanKey) -> str:
    return f"{key[0][:12]} p{key[1]} n{key[2]}"


def _weight(config: AleConfig, fidelity: Fidelity) -> float:
    return float(getattr(config.rulebook.fidelity_weights, fidelity.value))


def _inputs_hash(
    plans: Sequence[PlanInput], seed: Rulebook | None, config: AleConfig, min_support: int
) -> str:
    h = hashlib.sha256()
    for p in plans:
        h.update(canonical_json(p.topology))
        h.update(canonical_json(p.metric))
        h.update(repr((p.weight, p.north_angle_deg)).encode("utf-8"))
    h.update(canonical_json(seed) if seed is not None else b"no-seed\n")
    h.update(canonical_json(config.rulebook))
    h.update(canonical_json(config.shape))
    h.update(str(min_support).encode("ascii"))
    return h.hexdigest()


def build_rulebook(
    topologies: Sequence[PlanTopology],
    plans_metric: Sequence[PlanGeometry],
    seed: Rulebook | None,
    config: AleConfig,
    *,
    min_support: int | None = None,
    north: Mapping[tuple[str, int], float] | None = None,
    skipped: Sequence[tuple[str, str]] = (),
    today: _dt.date | None = None,
) -> BuildResult:
    """Mine the statistics of ``topologies`` / ``plans_metric`` and blend them with ``seed``.

    Topologies and geometries are matched by ``(source_sha256, page, plan_index)``
    (order is irrelevant); ``north`` maps ``(source_sha256, page)`` to the north angle in
    degrees; ``skipped`` lists plans rejected upstream ``(label, reason)`` for the report;
    ``min_support`` defaults to ``config.rulebook.min_support``; ``today`` (UTC, shown in the
    report only) defaults to the current UTC date.
    """
    support_min = config.rulebook.min_support if min_support is None else min_support
    north = north or {}
    geoms: dict[PlanKey, PlanGeometry] = {}
    for g in plans_metric:
        geoms.setdefault((g.source_sha256, g.page, g.plan_index), g)
    seen: set[PlanKey] = set()
    plans: list[PlanInput] = []
    skip = list(skipped)
    for t in sorted(topologies, key=lambda t: (t.source_sha256, t.page, t.plan_index)):
        key = (t.source_sha256, t.page, t.plan_index)
        if key in seen:
            raise ValueError(f"duplicate topology for plan {_label(key)}")
        seen.add(key)
        geom = geoms.get(key)
        if geom is None or geom.scale_m_per_unit is None:
            skip.append((_label(key), REASON_NO_GEOMETRY))
            continue
        plans.append(
            PlanInput(
                topology=t,
                metric=geom.to_metric(),
                weight=_weight(config, t.fidelity),
                north_angle_deg=north.get((t.source_sha256, t.page)),
            )
        )
    blended = blend_rulebook(
        pairs=adjacency_stats(plans),
        shapes=shape_stats(plans),
        orientation=orientation_stats(plans),
        core=core_offset_stats(plans),
        seed=seed,
        config=config,
        min_support=support_min,
    )
    day = today if today is not None else _dt.datetime.now(_dt.UTC).date()
    digest = _inputs_hash(plans, seed, config, support_min)
    mix = Counter(p.topology.fidelity for p in plans)
    rulebook = Rulebook(
        version=f"mined-{digest[:12]}",
        kind="blended" if seed is not None else "mined",
        n_plans=len(plans),
        source_mix={f: mix[f] for f in Fidelity if mix[f]},
        types=blended.types,
        adjacency=blended.adjacency,
        core_offset=blended.core_offset,
    )
    report = render_report(
        ReportInputs(
            rulebook=rulebook,
            blended=blended,
            config=config,
            min_support=support_min,
            seed_version=None if seed is None else seed.version,
            build_date=day.isoformat(),
            used=[(_label(p.key), p.topology.fidelity, p.weight, p.north_angle_deg) for p in plans],
            skipped=sorted(skip),
        )
    )
    return BuildResult(rulebook=rulebook, report_md=report)


# --------------------------------------------------------------------------- workspace run


def load_seed(path: Path) -> Rulebook:
    """Read and validate a seed rulebook YAML file (:class:`SeedError` on failure)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise SeedError(f"cannot read {path.name}: {exc}") from exc
    try:
        return load_yaml(Rulebook, text)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        loc = ".".join(str(p) for p in first["loc"]) or "<root>"
        raise SeedError(f"{path.name}: invalid rulebook ({loc}: {first['msg']})") from exc
    except Exception as exc:  # YAML syntax errors
        raise SeedError(f"{path.name}: invalid YAML ({exc})") from exc


def _north_of(meta: Mapping[str, Any], page: int) -> float | None:
    pages = meta.get("pages", {})
    page_meta = pages.get(str(page), {}) if isinstance(pages, dict) else {}
    value = page_meta.get("north_angle_deg", meta.get("north_angle_deg"))
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _units(ws: Workspace) -> list[tuple[str, int, dict[str, Any]]]:
    uri = ws.path(CORPUS_FILENAME).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version < 1:
            return []
        rows = conn.execute(
            "SELECT u.sha256, u.page, f.meta_json FROM units u JOIN files f "
            "ON f.sha256 = u.sha256 WHERE u.status = ? AND f.excluded = 0 "
            "ORDER BY u.sha256, u.page",
            (FileStatus.EXTRACTED.value,),
        ).fetchall()
    out: list[tuple[str, int, dict[str, Any]]] = []
    for sha, page, meta in rows:
        try:
            parsed = json.loads(meta) if meta else {}
        except json.JSONDecodeError:
            parsed = {}
        out.append((str(sha), int(page), parsed if isinstance(parsed, dict) else {}))
    return out


def _plan_files(ws: Workspace, sha: str, page: int) -> list[Path]:
    folder = ws.path("extracted", sha, str(page))
    if not folder.is_dir():
        return []
    dirs = sorted(
        (c for c in folder.iterdir() if c.is_dir() and c.name.isdigit()), key=lambda c: int(c.name)
    )
    return [d / "plan.json" for d in dirs if (d / "plan.json").is_file()]


_SQL_SCHEMA = """
CREATE TABLE plans (
    source_sha256 TEXT NOT NULL, page INTEGER NOT NULL, plan_index INTEGER NOT NULL,
    fidelity TEXT NOT NULL, weight REAL NOT NULL, north_angle_deg REAL,
    PRIMARY KEY (source_sha256, page, plan_index)
);
CREATE TABLE rooms (
    source_sha256 TEXT NOT NULL, page INTEGER NOT NULL, plan_index INTEGER NOT NULL,
    room_id TEXT NOT NULL, type TEXT, area_m2 REAL NOT NULL, aspect REAL,
    facade_m REAL NOT NULL, facade_n_m REAL, facade_e_m REAL, facade_s_m REAL, facade_w_m REAL,
    PRIMARY KEY (source_sha256, page, plan_index, room_id)
);
CREATE TABLE contacts (
    source_sha256 TEXT NOT NULL, page INTEGER NOT NULL, plan_index INTEGER NOT NULL,
    a TEXT NOT NULL, b TEXT NOT NULL, kind TEXT NOT NULL, shared_m REAL NOT NULL,
    openings INTEGER NOT NULL,
    PRIMARY KEY (source_sha256, page, plan_index, a, b)
);
"""


def _write_sqlite(path: Path, plans: Sequence[PlanInput]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with closing(sqlite3.connect(tmp)) as conn:
        conn.executescript(_SQL_SCHEMA)
        for p in plans:
            sha, page, idx = p.key
            t = p.topology
            conn.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                (sha, page, idx, t.fidelity.value, p.weight, p.north_angle_deg),
            )
            facade = dict(t.exterior)
            by_bearing = (
                room_facades(p.metric, p.north_angle_deg) if p.north_angle_deg is not None else {}
            )
            polys = {r.id: r.polygon for r in p.metric.rooms}
            for rid, rtype, area in t.rooms:
                poly = polys.get(rid)
                aspect = (
                    room_aspect(shapely.Polygon(poly.exterior, poly.holes))
                    if poly is not None
                    else None
                )
                fb = by_bearing.get(rid)
                conn.execute(
                    "INSERT INTO rooms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sha,
                        page,
                        idx,
                        rid,
                        rtype,
                        area,
                        aspect,
                        facade.get(rid, 0.0),
                        *((None if fb is None else fb.get(b, 0.0)) for b in BEARINGS),
                    ),
                )
            for c in t.contacts:
                conn.execute(
                    "INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (sha, page, idx, c.a, c.b, c.kind.value, c.shared_m, c.openings),
                )
        conn.commit()
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def run_build(
    ws: Workspace,
    *,
    seed: Rulebook | None = None,
    min_support: int | None = None,
    today: _dt.date | None = None,
) -> RunResult:
    """Build the rulebook of a workspace and write the three output files."""
    topologies: list[PlanTopology] = []
    metrics: list[PlanGeometry] = []
    north: dict[tuple[str, int], float] = {}
    skipped: list[tuple[str, str]] = []
    for sha, page, meta in _units(ws):
        angle = _north_of(meta, page)
        if angle is not None:
            north[(sha, page)] = angle
        for path in _plan_files(ws, sha, page):
            key: PlanKey = (sha, page, int(path.parent.name))
            try:
                plan = PlanGeometry.model_validate_json(path.read_bytes())
            except (OSError, ValidationError):
                skipped.append((_label(key), REASON_BAD_PLAN))
                continue
            topo = extract_topology(plan, ws.config)
            if topo is None:
                skipped.append((_label(key), REASON_NO_SCALE))
                continue
            topologies.append(topo)
            metrics.append(plan.to_metric())
    result = build_rulebook(
        topologies,
        metrics,
        seed,
        ws.config,
        min_support=min_support,
        north=north,
        skipped=skipped,
        today=today,
    )
    out_dir = ws.path("rulebook")
    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = out_dir / "rulebook.yaml"
    report_path = out_dir / "report.md"
    db_path = out_dir / "rulebook.sqlite"
    _write_text(yaml_path, dump_yaml(result.rulebook))
    _write_text(report_path, result.report_md)
    plans = sorted(
        (
            PlanInput(
                topology=t,
                metric=m,
                weight=_weight(ws.config, t.fidelity),
                north_angle_deg=north.get((t.source_sha256, t.page)),
            )
            for t, m in zip(topologies, metrics, strict=True)
        ),
        key=lambda p: p.key,
    )
    _write_sqlite(db_path, plans)
    return RunResult(
        result=result,
        used=result.rulebook.n_plans,
        skipped=tuple(sorted(skipped)),
        files=(yaml_path, report_path, db_path),
    )
