"""Exact unit conversions between metres, millimetres and integer grid modules.

External units are metres (m) and square metres (m²). Geometry internals use integer
modules of ``module_mm`` millimetres. All arithmetic is exact: inputs are converted to
``decimal.Decimal`` (floats through ``str(x)``) and rounded through ``fractions.Fraction``;
no float arithmetic is performed.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from fractions import Fraction

__all__ = [
    "MODULE_MM_MAX",
    "MODULE_MM_MIN",
    "NotOnGridError",
    "Rounding",
    "cells_to_m2",
    "check_module_mm",
    "m2_to_mm2",
    "m_to_mm",
    "m_to_modules",
    "mm2_to_m2",
    "mm_to_m",
    "mm_to_modules",
    "modules_to_m",
    "modules_to_mm",
    "to_decimal",
]

MODULE_MM_MIN = 100
MODULE_MM_MAX = 1200
_PREC = 80  # decimal digits; far beyond any value handled here, so products are exact


class Rounding(StrEnum):
    """Rounding mode for conversions onto the integer grid."""

    EXACT = "EXACT"
    FLOOR = "FLOOR"
    CEIL = "CEIL"
    NEAREST = "NEAREST"  # round-half-even


class NotOnGridError(ValueError):
    """Raised by ``Rounding.EXACT`` when a length is not a whole number of modules."""


def to_decimal(x: float | int | str | Decimal) -> Decimal:
    """Convert a number (metres, m², ... — unit-agnostic) to an exact finite ``Decimal``.

    Floats go through ``str(x)`` (shortest repr), so ``1.8`` becomes ``Decimal("1.8")``.
    Bools are rejected with ``TypeError``; non-finite values with ``ValueError``.
    """
    if isinstance(x, bool):
        raise TypeError("bool is not a number")
    if isinstance(x, Decimal):
        d = x
    elif isinstance(x, int):
        d = Decimal(x)
    elif isinstance(x, float):
        d = Decimal(str(x))
    elif isinstance(x, str):
        try:
            d = Decimal(x.strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a number: {x!r}") from exc
    else:
        raise TypeError(f"unsupported number type: {type(x).__name__}")
    if not d.is_finite():
        raise ValueError(f"not a finite number: {x!r}")
    return d


def _scaled(x: float | int | str | Decimal, factor: int) -> Fraction:
    """Exact value of ``x * factor`` as a Fraction."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return Fraction(to_decimal(x) * factor)


def _round(value: Fraction, mode: Rounding, what: str) -> int:
    if mode is Rounding.EXACT:
        if value.denominator != 1:
            raise NotOnGridError(what)
        return value.numerator
    if mode is Rounding.FLOOR:
        return math.floor(value)
    if mode is Rounding.CEIL:
        return math.ceil(value)
    if mode is Rounding.NEAREST:
        return round(value)  # Fraction.__round__ is round-half-even
    raise ValueError(f"unknown rounding mode {mode!r}")  # pragma: no cover


def _check_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return value


def check_module_mm(module_mm: object) -> int:
    """Validate a module size in millimetres: an ``int`` in ``100..1200`` (else ``ValueError``)."""
    if isinstance(module_mm, bool) or not isinstance(module_mm, int):
        raise ValueError(f"module_mm must be an int in 100..1200, got {module_mm!r}")
    if not MODULE_MM_MIN <= module_mm <= MODULE_MM_MAX:
        raise ValueError(f"module_mm must be an int in 100..1200, got {module_mm!r}")
    return module_mm


def m_to_mm(x: float | int | str | Decimal) -> int:
    """Metres → millimetres, rounded half-even to 1 mm."""
    return round(_scaled(x, 1000))


def mm_to_m(mm: int) -> float:
    """Millimetres → metres (``float(Decimal(mm) / 1000)``)."""
    _check_int("mm", mm)
    with localcontext() as ctx:
        ctx.prec = _PREC
        return float(Decimal(mm) / 1000)


def m2_to_mm2(x: float | int | str | Decimal) -> int:
    """Square metres → square millimetres, rounded half-even to 1 mm²."""
    return round(_scaled(x, 1_000_000))


def mm2_to_m2(mm2: int) -> float:
    """Square millimetres → square metres."""
    _check_int("mm2", mm2)
    with localcontext() as ctx:
        ctx.prec = _PREC
        return float(Decimal(mm2) / 1_000_000)


def mm_to_modules(mm: int, module_mm: int, mode: Rounding = Rounding.EXACT) -> int:
    """Millimetres → number of modules of ``module_mm`` mm, using rounding ``mode``.

    ``Rounding.EXACT`` raises ``NotOnGridError`` if ``mm`` is not a whole number of modules.
    """
    _check_int("mm", mm)
    module = check_module_mm(module_mm)
    value = Fraction(mm, module)
    return _round(value, Rounding(mode), f"{mm} mm is not a multiple of module {module} mm")


def m_to_modules(
    x: float | int | str | Decimal, module_mm: int, mode: Rounding = Rounding.EXACT
) -> int:
    """Metres → number of modules of ``module_mm`` mm (exact, no intermediate mm rounding).

    ``Rounding.EXACT`` raises ``NotOnGridError`` if ``x`` is not a whole number of modules.
    """
    module = check_module_mm(module_mm)
    value = _scaled(x, 1000) / module
    return _round(value, Rounding(mode), f"{x} m is not a multiple of module {module} mm")


def modules_to_mm(n: int, module_mm: int) -> int:
    """Number of modules → millimetres."""
    _check_int("n", n)
    return n * check_module_mm(module_mm)


def modules_to_m(n: int, module_mm: int) -> float:
    """Number of modules → metres."""
    return mm_to_m(modules_to_mm(n, module_mm))


def cells_to_m2(n_cells: int, module_mm: int) -> float:
    """Number of module² cells → square metres."""
    _check_int("n_cells", n_cells)
    module = check_module_mm(module_mm)
    return mm2_to_m2(n_cells * module * module)
