"""Tests M402, M413-M415 (Ticket M.4): the bay planner seen from ``run_plans`` and ``ale stack``.

Kernel, catalogue and property tests are in ``tests/bayplan``. Here: the CLI (exit codes, files,
``--planner``), the routing of non-bar floors to the engine, the byte identity of the engine
path, the report and the determinism of the bay planner. Cases A and B are shared with the
kernel tests through ``tests/bayplan/bay_cases.py``.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

_BAYPLAN = Path(__file__).resolve().parent.parent / "bayplan"
if str(_BAYPLAN) not in sys.path:
    sys.path.insert(0, str(_BAYPLAN))

import bar_case  # noqa: E402
import bay_cases as bc  # noqa: E402
import plans_case as pc  # noqa: E402

from ale.cli import app  # noqa: E402
from ale.contracts.serialization import dump_yaml  # noqa: E402
from ale.parti.evaluate import neutral_rulebook  # noqa: E402
from ale.stack import parse_building, parse_rules, run_stack  # noqa: E402
from ale.stack.plans import PlansResult, run_plans  # noqa: E402
from ale.stack.rules import RhythmInputError  # noqa: E402

#: sha256 of every file of ``ale stack`` (no ``--plans``) on case B at the base commit 7531321.
BASE_B_SHA256 = {
    "floor_00/diagram.svg": "26458ed54a023ccd52e6fe7d88ae5894c895cdb28efe122070eca841f80b29e0",
    "floor_00/programme.xlsx": "d183654edbc3df57600fb78d0e57c80555ee84dcac42897c023d76f3a19ba814",
    "floor_00/site.yaml": "b5467fc0e4c5f4b0d8876b614c3733ccbb634edc3e3b9086319f396c69cfeb93",
    "floor_01/diagram.svg": "420741ffbbd54d09de2de88d8accd0bd15b3462657b22eca55efc7061e32f221",
    "floor_01/programme.xlsx": "39830a030f018321699b1c65d3706b5070703cf9bed5a5cdb64b1f9913b01863",
    "floor_01/site.yaml": "f71ee9cb080350d50d7c0597f830d610cf2d5137cbb7c6d5712f9d1e57252f64",
    "floor_02/diagram.svg": "4b8a5c6f9e07857098847e37c5c9d3f64e52c217998f37bae2e7ebe9e5e14ab8",
    "floor_02/programme.xlsx": "9ebda9ff72a1901500569b18b3018e33a74e90f21d6a35553e4990bb32a2ad44",
    "floor_02/site.yaml": "f71ee9cb080350d50d7c0597f830d610cf2d5137cbb7c6d5712f9d1e57252f64",
    "floor_03/diagram.svg": "4ae8a7de745a2ff9d4f15b430613a6b6b88f07ce5dd7850a219375b3c98225c6",
    "floor_03/programme.xlsx": "cb2d4270a23fac74e0f174f2187d2c2753a06051cff702d197118c8ea265aaff",
    "floor_03/site.yaml": "d85df065ca47ea52230f144d1d6ccf4f8d2fb97959b38b1044c46da89d575d64",
    "stack.svg": "47fd3711f2ff399dea18e5d174be8b826e0e8811dcbef9ebeb8423e705d0f787",
    "stacking.md": "a0a56cca9eecc0729c5dd21b21ede1aff2e81f2c67b693e7be935aeb21092f88",
}
PLAN_FILES = ("layout.json", "layout.dxf", "preview.svg", "report.md")


def _cli(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def _stack_args(d: Path, out: Path, name: str, *extra: str) -> list[str]:
    prog, bld, rules, rb = bc.write_case(name, d)
    return [
        "stack",
        "--program",
        str(prog),
        "--building",
        str(bld),
        "--rules",
        str(rules),
        "--out",
        str(out),
        "--rulebook",
        str(rb),
        *extra,
    ]


class CliRun:
    def __init__(self, exit_code: int, out: Path, seconds: float, output: str) -> None:
        self.exit_code = exit_code
        self.out = out
        self.seconds = seconds
        self.output = output


def _run(tmp: Path, name: str, tag: str, *extra: str) -> CliRun:
    out = tmp / f"out_{name}_{tag}"
    t0 = time.monotonic()
    res = _cli(*_stack_args(tmp / f"in_{name}", out, name, "--plans", *extra))
    return CliRun(res.exit_code, out, time.monotonic() - t0, res.output)


@pytest.fixture(scope="module")
def cli(tmp_path_factory: pytest.TempPathFactory) -> dict[str, CliRun]:
    tmp = tmp_path_factory.mktemp("m4_cli")
    return {
        "A": _run(tmp, "A", "1"),
        "B": _run(tmp, "B", "1"),
        "B2": _run(tmp, "B", "2"),
    }


# --------------------------------------------------------------------------------- M402
def test_M402_exit_codes_and_files(cli: dict[str, CliRun]) -> None:
    assert cli["A"].exit_code == 0
    assert cli["B"].exit_code == 1  # unplaced rooms are hard misses, files still written
    assert "non placée" in cli["B"].output
    for key in ("A", "B"):
        out = cli[key].out
        assert (out / "plans.md").exists() and (out / "stacking.md").exists()
        for level in range(4):
            for f in PLAN_FILES:
                assert (out / f"floor_{level:02d}" / "plan" / f).exists(), (key, level, f)


# --------------------------------------------------------------------------------- M413
def test_M413_non_bar_floors_go_to_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ale.stack import plans as plans_mod

    calls: list[int] = []
    real = plans_mod._seed_and_anneal

    def spy(*a: Any, **kw: Any) -> Any:
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(plans_mod, "_seed_and_anneal", spy)
    prog = pc.program()
    rb = tmp_path / "rb.yaml"
    rb.write_text(dump_yaml(neutral_rulebook(prog)), encoding="utf-8")
    res = run_stack(
        prog, parse_building(pc.building_dict()), parse_rules(pc.RULES), strict_solids=True
    )
    pr, _ = run_plans(res, rb, tmp_path / "out", budget_s=1.0, planner="bay")
    assert len(calls) == len(pr.floors) == 4
    assert all(p.planner == "engine" and p.bay is None for p in pr.floors)
    assert all(p.why for p in pr.floors)
    text = (tmp_path / "out" / "plans.md").read_text(encoding="utf-8")
    assert "Planificateur : moteur de plans exacts" in text
    assert "barre" in text  # the reason: not a bar


def test_M413_engine_planner_never_calls_the_bay_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ale.bayplan as bayplan
    from ale.stack import plans as plans_mod

    def boom(*a: Any, **kw: Any) -> Any:
        raise AssertionError("bay planner called")

    def stop(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("engine reached")

    monkeypatch.setattr(bayplan, "plan_bar", boom)
    monkeypatch.setattr(plans_mod, "_seed_and_anneal", stop)
    prog, bld, rules = bc.case_inputs("A")
    rb = tmp_path / "rb.yaml"
    rb.write_text(dump_yaml(neutral_rulebook(prog)), encoding="utf-8")
    res = run_stack(prog, parse_building(bld), parse_rules(rules), strict_solids=True)
    pr, _ = run_plans(res, rb, tmp_path / "out", budget_s=1.0)  # default planner: engine
    assert all("engine reached" in p.message for p in pr.floors)
    assert all(p.planner == "engine" and p.bay is None for p in pr.floors)
    text = (tmp_path / "out" / "plans.md").read_text(encoding="utf-8")
    assert "Plans en travées" not in text


def test_M413_stack_without_plans_is_byte_identical(tmp_path: Path) -> None:
    prog, bld, rules, _rb = bar_case.write_inputs(tmp_path / "in")
    out = tmp_path / "out"
    res = _cli(
        "stack", "--program", str(prog), "--building", str(bld), "--rules", str(rules),
        "--out", str(out),
    )  # fmt: skip
    assert res.exit_code == 0
    got = {
        str(f.relative_to(out)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(out.rglob("*"))
        if f.is_file()
    }
    assert got == BASE_B_SHA256


def test_M413_cli_planner_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ale.stack import plans as plans_mod

    seen: list[str] = []

    def fake(result: Any, rulebook: Path, out: Path, **kw: Any) -> Any:
        seen.append(kw["planner"])
        return PlansResult(floors=(), vertical=(), vertical_ok=True), result

    monkeypatch.setattr(plans_mod, "run_plans", fake)
    base = _stack_args(tmp_path / "in", tmp_path / "out", "A", "--plans")
    assert _cli(*base).exit_code == 0 and seen == ["bay"]  # default planner: bay
    assert _cli(*base, "--planner", "engine").exit_code == 0 and seen[-1] == "engine"
    bad = _cli(*base, "--planner", "nope")
    assert bad.exit_code == 2


def test_rules_keys_are_validated(tmp_path: Path) -> None:
    rules = parse_rules({"corridor_m": 2.4, "sketch_tolerance_pct": 5})
    assert rules.corridor_m == 2.4 and rules.sketch_tolerance_pct == 5
    for bad in ({"corridor_m": 1.5}, {"corridor_m": -1}, {"sketch_tolerance_pct": 25}):
        with pytest.raises(RhythmInputError) as exc:
            parse_rules(bad)
        assert "«" in str(exc.value)
    args = _stack_args(tmp_path / "in", tmp_path / "out", "A")
    rules_path = Path(args[args.index("--rules") + 1])
    rules_path.write_text("corridor_m: 1.5\n", encoding="utf-8")
    res = _cli(*args)
    assert res.exit_code == 2 and "corridor_m" in res.output


# --------------------------------------------------------------------------------- M414
@pytest.mark.parametrize("key", ["A", "B"])
def test_M414_report_items(cli: dict[str, CliRun], key: str) -> None:
    text = (cli[key].out / "plans.md").read_text(encoding="utf-8")
    assert "## Plans en travées (M.4)" in text
    for needle in (
        "Planificateur : plan en travées",
        "Section (19.2 m de profondeur)",
        "d_f = 4.8 m",
        "Travées de façade",
        "non placée(s)",
        "À ajuster",
        "Réserve :",
        "Circulation :",
        "palier",
        "reliquat",
        "Couloir rétréci le long du noyau",
        "cul-de-sac",
        "distance d'une pièce au noyau",
        "même groupe en plusieurs tronçons",
        "Cloisons de façade longue",
        "Entrée (",
        "Borne d'empilement par type",
        "Trame et empilement",
    ):
        assert needle in text, (key, needle)
    assert text.count("### Niveau") == 4


# --------------------------------------------------------------------------------- M415
def test_M415_runs_are_byte_identical_and_fast(cli: dict[str, CliRun]) -> None:
    a, b = cli["B"].out, cli["B2"].out
    assert (a / "plans.md").read_bytes() == (b / "plans.md").read_bytes()
    dxf_same = []
    for level in range(4):
        for f in PLAN_FILES:
            fa = a / f"floor_{level:02d}" / "plan" / f
            fb = b / f"floor_{level:02d}" / "plan" / f
            if f == "layout.dxf":
                dxf_same.append(fa.read_bytes() == fb.read_bytes())
            else:
                assert fa.read_bytes() == fb.read_bytes(), (level, f)
    print("DXF byte-identical across runs:", dxf_same)
    assert cli["B"].seconds <= 30.0


def test_M415_bay_floor_times(tmp_path: Path) -> None:
    pr, _used, _rb, _prog = bc.run_case("B", tmp_path / "b")
    assert all(p.elapsed_s <= 5.0 for p in pr.floors)
