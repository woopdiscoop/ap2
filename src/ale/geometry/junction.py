"""Piece frames and L-shape spine alignment (RD 3.3 section 5.5).

A piece's local frame has ``u`` along its spine (length ``L``) and ``v`` across it (depth
``P``), origin at the piece's min corner. J2: the secondary spine occupies the same
absolute band across the (collinear) spines as the primary's. J1: the primary's junction
finger fixes an absolute band along the primary spine, which becomes the band of the
(perpendicular) secondary spine.
"""

from __future__ import annotations

from ale.contracts.footprint import Piece
from ale.contracts.geometry import ModuleRect

__all__ = [
    "across_origin",
    "along_origin",
    "band_fits",
    "frame",
    "j1_secondary_depth",
    "j2_secondary_depth",
    "to_abs",
]


def frame(piece: Piece) -> tuple[int, int]:
    """``(L, P)``: length along the spine and depth across it, in modules."""
    r = piece.rect
    return (r.w, r.h) if piece.spine_axis == "X" else (r.h, r.w)


def along_origin(piece: Piece) -> int:
    """Absolute coordinate of ``u = 0``."""
    return piece.rect.x if piece.spine_axis == "X" else piece.rect.y


def across_origin(piece: Piece) -> int:
    """Absolute coordinate of ``v = 0``."""
    return piece.rect.y if piece.spine_axis == "X" else piece.rect.x


def to_abs(piece: Piece, u: int, v: int, du: int, dv: int) -> ModuleRect:
    """Local ``(u, v, du, dv)`` → footprint rectangle (axis X: x = u; axis Y: x = v)."""
    r = piece.rect
    if piece.spine_axis == "X":
        return ModuleRect(r.x + u, r.y + v, du, dv)
    return ModuleRect(r.x + v, r.y + u, dv, du)


def band_fits(piece: Piece, d_a: int, s: int) -> bool:
    """Whether a spine band ``[d_a, d_a + s)`` across ``piece`` lies inside it."""
    return d_a >= 0 and d_a + s <= frame(piece)[1]


def j2_secondary_depth(primary: Piece, secondary: Piece, d_a: int) -> int:
    """Secondary ``D_A`` putting its spine in the same absolute band as the primary's."""
    return across_origin(primary) + d_a - across_origin(secondary)


def j1_secondary_depth(primary: Piece, secondary: Piece, junction_u: int) -> int:
    """Secondary ``D_A`` aligning its spine with the junction finger at ``junction_u``."""
    return along_origin(primary) + junction_u - across_origin(secondary)
