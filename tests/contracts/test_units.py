"""Tests U01-U06: exact unit conversions and the float-modulo ban."""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ale.contracts.units import (
    NotOnGridError,
    Rounding,
    cells_to_m2,
    m2_to_mm2,
    m_to_mm,
    m_to_modules,
    mm2_to_m2,
    mm_to_m,
    mm_to_modules,
    modules_to_m,
    modules_to_mm,
    to_decimal,
)

CONTRACTS_SRC = Path(__file__).resolve().parents[2] / "src" / "ale" / "contracts"


def test_U01_exact_modules() -> None:
    assert m_to_modules(1.8, 600) == 3
    assert m_to_modules(0.6, 600) == 1
    assert m_to_modules("12.0", 600) == 20
    with pytest.raises(NotOnGridError) as exc:
        m_to_modules(1.75, 600)
    assert "1.75" in str(exc.value)
    assert "600" in str(exc.value)
    with pytest.raises(NotOnGridError, match="900"):
        mm_to_modules(900, 600)
    assert m_to_modules(Decimal("2.4"), 600) == 4
    assert m_to_modules(3, 600) == 5


def test_U02_rounding_modes() -> None:
    assert m_to_modules(1.75, 600, Rounding.FLOOR) == 2
    assert m_to_modules(1.75, 600, Rounding.CEIL) == 3
    assert m_to_modules(1.75, 600, Rounding.NEAREST) == 3
    assert mm_to_modules(900, 600, Rounding.NEAREST) == 2
    assert mm_to_modules(1500, 600, Rounding.NEAREST) == 2
    assert mm_to_modules(-900, 600, Rounding.FLOOR) == -2
    assert mm_to_modules(-900, 600, Rounding.CEIL) == -1


@settings(max_examples=300, derandomize=True, deadline=None)
@given(
    n=st.integers(min_value=-(10**6), max_value=10**6), mm=st.sampled_from([100, 300, 600, 1200])
)
def test_U03_roundtrip_property(n: int, mm: int) -> None:
    assert m_to_modules(modules_to_m(n, mm), mm) == n
    assert mm_to_modules(modules_to_mm(n, mm), mm) == n


def test_U04_area_exact() -> None:
    assert cells_to_m2(9, 600) == 3.24
    assert m2_to_mm2(12.6) == 12_600_000
    assert mm2_to_m2(8_640_000) == 8.64
    assert m_to_mm(1.2345) == 1234  # half-even: 1234.5 -> 1234
    assert m_to_mm(1.2355) == 1236  # half-even: 1235.5 -> 1236
    assert mm_to_m(1250) == 1.25
    assert modules_to_m(4, 600) == 2.4


@pytest.mark.parametrize("bad", [99, 1201, 600.0, True, "600"])
def test_U05_module_range(bad: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        m_to_modules(1.2, bad)  # type: ignore[arg-type]
    with pytest.raises((ValueError, TypeError)):
        mm_to_modules(1200, bad)  # type: ignore[arg-type]
    with pytest.raises((ValueError, TypeError)):
        cells_to_m2(1, bad)  # type: ignore[arg-type]


def test_U05_input_types() -> None:
    with pytest.raises(TypeError):
        to_decimal(True)
    with pytest.raises(TypeError):
        to_decimal([1])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        to_decimal("abc")
    with pytest.raises(ValueError):
        to_decimal(float("nan"))
    with pytest.raises(TypeError):
        mm_to_m(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        mm_to_modules(True, 600)
    assert to_decimal(" 1.50 ") == Decimal("1.50")


# --------------------------------------------------------------------------- U06 checker

_MARKER = "# int-mod"


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return f"{_call_name(func.value)}.{func.attr}"
    return ""


def find_modulo_violations(source: str, filename: str = "<src>") -> list[str]:
    """Return violations of the float-modulo rule in ``source``.

    Every ``%`` / ``%=`` and ``divmod`` must sit on a line ending with ``# int-mod``;
    ``math.fmod`` (or an imported ``fmod``) is forbidden outright.
    """
    tree = ast.parse(source, filename)
    lines = source.splitlines()
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "math":
            if any(alias.name == "fmod" for alias in node.names):
                out.append(f"{filename}:{node.lineno}: math.fmod is forbidden")
            continue
        if isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Mod):
            what = "%"
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in ("math.fmod", "fmod"):
                out.append(f"{filename}:{node.lineno}: math.fmod is forbidden")
                continue
            if name != "divmod":
                continue
            what = "divmod"
        else:
            continue
        if not lines[node.lineno - 1].rstrip().endswith(_MARKER):
            out.append(f"{filename}:{node.lineno}: {what} without '{_MARKER}' marker")
    return out


@pytest.mark.parametrize(
    ("source", "n_violations"),
    [
        ("x = a % b\n", 1),
        ("x = a % b  # int-mod\n", 0),
        ("x %= 3\n", 1),
        ("x %= 3  # int-mod\n", 0),
        ("q, r = divmod(a, b)\n", 1),
        ("q, r = divmod(a, b)  # int-mod\n", 0),
        ("import math\ny = math.fmod(a, b)  # int-mod\n", 1),
        ("from math import fmod\ny = fmod(a, b)  # int-mod\n", 2),
        ("x = a // b\ny = f(a)\n", 0),
    ],
)
def test_U06_checker_detects_planted_violations(source: str, n_violations: int) -> None:
    assert len(find_modulo_violations(source)) == n_violations


def test_U06_no_float_modulo() -> None:
    files = sorted(CONTRACTS_SRC.rglob("*.py"))
    assert files, "no source files found"
    violations: list[str] = []
    for f in files:
        violations += find_modulo_violations(f.read_text(encoding="utf-8"), str(f))
    assert violations == []
