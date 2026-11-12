"""The building description of the stacking phase (Ticket M.1, RD section 3).

Module-local model (not a contract): per-floor outlines, one core, entrances, floor height.
Loader errors are in French.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator
from shapely import Polygon as ShPolygon
from shapely import box

from ale.contracts.geometry import Polygon
from ale.contracts.models import CoreSpec, Entrance
from ale.stack.rules import StackInputError

__all__ = ["SCHEMA", "Building", "Floor", "dump_building", "load_building", "parse_building"]

SCHEMA = "ale.building/1"
_EPS = 1e-6
_CFG = ConfigDict(extra="forbid", frozen=True)


class Floor(BaseModel):
    """One storey: its level (0 = ground) and its outline (metres, CCW, no hole)."""

    model_config = _CFG

    level: StrictInt
    footprint: Polygon


class Building(BaseModel):
    """Per-floor outlines and the one vertical core (U-14), validated."""

    model_config = _CFG

    schema_version: Literal["ale.building/1"] = "ale.building/1"
    north_angle_deg: Annotated[float, Field(ge=0.0, lt=360.0)] = 0.0
    access_edge: StrictInt = 0
    entrances: tuple[Entrance, ...] = ()
    floor_height_m: Annotated[float, Field(gt=0.0)] = 3.5
    core: CoreSpec
    floors: tuple[Floor, ...]

    @model_validator(mode="after")
    def _check(self) -> Building:
        if not self.floors:
            raise ValueError("le bâtiment n'a aucun niveau")
        levels = [f.level for f in self.floors]
        if levels != list(range(len(levels))):
            raise ValueError(
                f"niveaux non contigus ou non ordonnés : {levels} (attendu 0..{len(levels) - 1})"
            )
        n_ext = len(self.floors[0].footprint.exterior)
        if not 0 <= self.access_edge < n_ext:
            raise ValueError(f"access_edge {self.access_edge} hors de 0..{n_ext - 1}")
        core = self.core_box()
        for f in self.floors:
            _rectilinear(f.footprint.exterior, f.level)
            if f.footprint.holes:
                raise ValueError(f"niveau {f.level} : les contours avec trous ne sont pas gérés")
            if not _poly(f).buffer(_EPS).covers(core):
                raise ValueError(f"le noyau {self.core.id} sort du contour du niveau {f.level}")
        for lo, up in zip(self.floors, self.floors[1:], strict=False):
            if not _poly(lo).buffer(_EPS).covers(_poly(up)):
                raise ValueError(
                    f"le contour du niveau {up.level} ne tient pas dans celui du niveau "
                    f"{lo.level} (les terrasses reculent vers le haut)"
                )
        return self

    @property
    def n_floors(self) -> int:
        return len(self.floors)

    def outline(self, level: int) -> ShPolygon:
        """Outline of ``level`` as a shapely polygon."""
        return _poly(self.floors[level])

    def core_box(self) -> ShPolygon:
        """The core rectangle as a shapely polygon."""
        x, y, w, h = self.core.rect
        return box(x, y, x + w, y + h)


def _poly(f: Floor) -> ShPolygon:
    return ShPolygon(f.footprint.exterior)


def _rectilinear(ring: tuple[tuple[float, float], ...], level: int) -> None:
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if a[0] != b[0] and a[1] != b[1]:
            raise ValueError(f"niveau {level} : le contour doit être orthogonal ({a} -> {b})")


def _signed_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def _points(raw: Any, where: str, errors: list[str]) -> list[tuple[float, float]] | None:
    if isinstance(raw, dict):
        raw = raw.get("exterior")
    if not isinstance(raw, list) or len(raw) < 3:
        errors.append(f"{where} : liste d'au moins 3 points [x, y] attendue.")
        return None
    pts: list[tuple[float, float]] = []
    for p in raw:
        ok = (
            isinstance(p, list | tuple)
            and len(p) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) for v in p)
        )
        if not ok:
            errors.append(f"{where} : point invalide {p!r} (attendu [x, y] en mètres).")
            return None
        pts.append((float(p[0]), float(p[1])))
    return pts


def _core_list(data: dict[str, Any], errors: list[str]) -> list[Any]:
    if "core" in data and "cores" in data:
        errors.append("building.yaml : utilisez « core » ou « cores », pas les deux.")
    if "core" in data:
        cores: list[Any] = [data["core"]] if data["core"] is not None else []
    else:
        raw = data.get("cores")
        cores = list(raw) if isinstance(raw, list) else []
    if not cores:
        errors.append("building.yaml : aucun noyau (exactement un noyau est exigé, U-14).")
    elif len(cores) > 1:
        errors.append(
            f"building.yaml : {len(cores)} noyaux déclarés, exactement un est exigé (U-14) ; "
            "un noyau peut contenir plusieurs escaliers."
        )
    return cores


def _floors(data: dict[str, Any], access: int, errors: list[str]) -> tuple[list[Any], int]:
    raw = data.get("floors")
    floors: list[Any] = []
    if not isinstance(raw, list) or not raw:
        errors.append("building.yaml : « floors » doit être une liste non vide.")
        return floors, access
    for k, f in enumerate(raw):
        if not isinstance(f, dict) or "level" not in f or "footprint" not in f:
            errors.append(f"floors[{k}] : « level » et « footprint » sont exigés.")
            continue
        pts = _points(f["footprint"], f"floors[{k}].footprint", errors)
        if pts is None:
            continue
        if _signed_area(pts) < 0:
            pts.reverse()
            if k == 0:
                access = (len(pts) - 2 - access) % len(pts)
        floors.append({"level": f["level"], "footprint": {"exterior": pts}})
    return floors, access


def parse_building(data: Any) -> Building:
    """Build and validate a :class:`Building` from decoded YAML (French errors)."""
    if not isinstance(data, dict):
        raise StackInputError("building.yaml : le fichier doit contenir un dictionnaire.")
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA:
        errors.append(
            f"building.yaml : schema_version « {SCHEMA} » attendu (reçu "
            f"{data.get('schema_version')!r})."
        )
    cores = _core_list(data, errors)
    raw_access = data.get("access_edge", 0)
    access = raw_access if isinstance(raw_access, int) and not isinstance(raw_access, bool) else 0
    floors, access = _floors(data, access, errors)
    if errors:
        raise StackInputError(*errors)
    try:
        return Building.model_validate(
            {
                "schema_version": SCHEMA,
                "north_angle_deg": data.get("north_angle_deg", 0.0),
                "access_edge": access,
                "entrances": data.get("entrances", []),
                "floor_height_m": data.get("floor_height_m", 3.5),
                "core": cores[0],
                "floors": floors,
            }
        )
    except ValidationError as exc:
        raise StackInputError(*_french(exc)) from None


def _french(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(p) for p in err["loc"])
        msg = str(err["msg"]).removeprefix("Value error, ")
        out.append(f"building.yaml{' (' + loc + ')' if loc else ''} : {msg}.")
    return out


def load_building(path: Path) -> Building:
    """Read ``building.yaml`` (French errors via :class:`StackInputError`)."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError) as exc:
        raise StackInputError(f"building.yaml illisible : {exc}.") from None
    except yaml.YAMLError as exc:
        raise StackInputError(f"building.yaml : YAML invalide ({exc}).") from None
    return parse_building(data)


def dump_building(b: Building) -> str:
    """Deterministic ``building.yaml`` text."""
    data: dict[str, Any] = {
        "schema_version": b.schema_version,
        "north_angle_deg": b.north_angle_deg,
        "access_edge": b.access_edge,
        "entrances": [
            {"point": list(e.point), "label": e.label, "main": e.main} for e in b.entrances
        ],
        "floor_height_m": b.floor_height_m,
        "core": {"id": b.core.id, "rect": list(b.core.rect), "kind": b.core.kind},
        "floors": [
            {"level": f.level, "footprint": [list(p) for p in f.footprint.exterior]}
            for f in b.floors
        ],
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
