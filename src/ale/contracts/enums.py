"""Enumerations shared by every ALE contract (all ``StrEnum``, value == name)."""

from enum import StrEnum

__all__ = [
    "Bearing",
    "ContactKind",
    "EdgeKind",
    "Fidelity",
    "FileStatus",
    "Frame",
    "LabelSource",
    "MacroZone",
    "OpeningKind",
    "ScaleMethod",
    "SourceKind",
    "TypeCategory",
    "fidelity_of",
]


class SourceKind(StrEnum):
    """Kind of source file a plan was read from."""

    DWG = "DWG"
    DXF = "DXF"
    PDF_VECTOR = "PDF_VECTOR"
    PDF_SCANNED = "PDF_SCANNED"
    RASTER = "RASTER"


class FileStatus(StrEnum):
    """Processing status of a source file."""

    NEW = "NEW"
    EXTRACTED = "EXTRACTED"
    FAILED = "FAILED"
    EXCLUDED = "EXCLUDED"
    NEEDS_TOOL = "NEEDS_TOOL"


class ScaleMethod(StrEnum):
    """How the metres-per-native-unit scale of a plan was determined."""

    DRAWING_UNITS = "DRAWING_UNITS"
    META_CSV = "META_CSV"
    TITLE_BLOCK = "TITLE_BLOCK"
    SCALE_BAR = "SCALE_BAR"
    DIMENSION_TEXT = "DIMENSION_TEXT"
    DOOR_MEDIAN = "DOOR_MEDIAN"
    UNKNOWN = "UNKNOWN"


class LabelSource(StrEnum):
    """Origin of a room label."""

    CAD_TEXT = "CAD_TEXT"
    CAD_ZONE = "CAD_ZONE"
    PDF_TEXT = "PDF_TEXT"
    VLM = "VLM"
    MANUAL = "MANUAL"


class MacroZone(StrEnum):
    """Functional macro-zone of a room."""

    PUBLIC = "PUBLIC"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    SERVICES = "SERVICES"


class Bearing(StrEnum):
    """Compass bearing bin (true north based)."""

    N = "N"
    E = "E"
    S = "S"
    W = "W"


class EdgeKind(StrEnum):
    """Kind of an edge of the program/topology graph."""

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    AVOID = "AVOID"


class ContactKind(StrEnum):
    """Kind of an extracted topology edge between two rooms."""

    WALL = "WALL"
    DOOR = "DOOR"


class OpeningKind(StrEnum):
    """Kind of a wall opening."""

    DOOR = "DOOR"
    WINDOW = "WINDOW"


class Fidelity(StrEnum):
    """Source fidelity class."""

    CAD = "CAD"
    PDF_VECTOR = "PDF_VECTOR"
    RASTER = "RASTER"


class TypeCategory(StrEnum):
    """Category of a room type in the taxonomy."""

    ROOM = "ROOM"
    CIRCULATION = "CIRCULATION"
    VERTICAL = "VERTICAL"
    SPECIAL = "SPECIAL"


class Frame(StrEnum):
    """Native coordinate frame of a plan geometry."""

    Y_UP = "Y_UP"
    Y_DOWN = "Y_DOWN"


_FIDELITY: dict[SourceKind, Fidelity] = {
    SourceKind.DWG: Fidelity.CAD,
    SourceKind.DXF: Fidelity.CAD,
    SourceKind.PDF_VECTOR: Fidelity.PDF_VECTOR,
    SourceKind.PDF_SCANNED: Fidelity.RASTER,
    SourceKind.RASTER: Fidelity.RASTER,
}


def fidelity_of(kind: SourceKind) -> Fidelity:
    """Return the fidelity class of a source kind (unitless classification)."""
    return _FIDELITY[SourceKind(kind)]
