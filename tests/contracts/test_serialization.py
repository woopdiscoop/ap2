"""Tests J01-J06: canonical JSON, schemas, CLI helpers, lock, import cost."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
import yaml
from pydantic import BaseModel

from ale.contracts import export_schemas, lock, validate
from ale.contracts.enums import Bearing, Fidelity
from ale.contracts.models import Layout, PolishExpression
from ale.contracts.serialization import canonical_json, dump_yaml, round_floats
from ale.contracts.taxonomy import load_taxonomy
from ale.contracts.version import CONTRACTS_VERSION

# --------------------------------------------------------------------------- J01


def test_J01_canonical_bytes(h: SimpleNamespace) -> None:
    a = h.make_rulebook()
    data = a.model_dump()
    reversed_data = {
        **data,
        "types": {
            k: {**v, "orientation": dict(reversed(list(v["orientation"].items())))}
            for k, v in reversed(list(data["types"].items()))
        },
        "source_mix": dict(reversed(list(data["source_mix"].items()))),
    }
    b = type(a).model_validate(reversed_data)
    assert list(b.types) != list(a.types)
    assert list(b.source_mix) == [Fidelity.RASTER, Fidelity.CAD]
    assert next(iter(b.types["office"].orientation)) is Bearing.W
    out = canonical_json(a)
    assert out == canonical_json(b)
    assert out.endswith(b"\n")
    assert out.count(b"\n") == 1
    assert b", " not in out
    assert b'": ' not in out
    parsed = json.loads(out)
    assert list(parsed) == sorted(parsed)

    layout = h.make_layout()
    bad = layout.model_copy(
        update={"metrics": layout.metrics.model_copy(update={"total_cost": float("nan")})}
    )
    with pytest.raises(ValueError):
        canonical_json(bad)


def test_J01_float_rounding(h: SimpleNamespace) -> None:
    assert round_floats({"a": [0.1 + 0.2, 1, True, "x"], "b": 1 / 3}) == {
        "a": [0.3, 1, True, "x"],
        "b": 0.333333333,
    }
    out = canonical_json(h.make_program())
    assert "réunion".encode() in out  # ensure_ascii=False
    rounded = PolishExpression.model_validate_json(canonical_json(h.make_polish()))
    assert rounded == h.make_polish()


# --------------------------------------------------------------------------- J02


def test_J02_schema_no_drift(h: SimpleNamespace, tmp_path: Path) -> None:
    proc = h.run_module(["-m", "ale.contracts.export_schemas", "--check"])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    root = h.copy_package(tmp_path)
    target = root / "ale" / "contracts" / "schemas" / "Rulebook.schema.json"
    raw = bytearray(target.read_bytes())
    raw[10] = ord("X") if raw[10] != ord("X") else ord("Y")
    target.write_bytes(bytes(raw))
    proc = h.run_module(["-m", "ale.contracts.export_schemas", "--check"], pythonpath=root)
    assert proc.returncode == 1
    assert "Rulebook.schema.json" in proc.stdout


def test_J02_export_in_process(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert export_schemas.main(["--check"]) == 0
    out_dir = tmp_path / "schemas"
    assert export_schemas.export(out_dir, check=True) == 1  # missing files
    assert export_schemas.export(out_dir, check=False) == 0
    assert export_schemas.export(out_dir, check=True) == 0
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == sorted(f"{m.__name__}.schema.json" for m in export_schemas.SCHEMA_MODELS)
    for p in out_dir.iterdir():
        assert p.read_bytes() == (export_schemas.SCHEMA_DIR / p.name).read_bytes()
    (out_dir / "Layout.schema.json").write_text("{}\n", encoding="utf-8")
    assert export_schemas.export(out_dir, check=True) == 1
    assert "Layout.schema.json" in capsys.readouterr().out


# --------------------------------------------------------------------------- J03

SCHEMA_FOR = {
    "RoomSpec": "RoomSpec",
    "Program": "Program",
    "SiteSpec": "SiteSpec",
    "Layout": "Layout",
    "PlanGeometry": "PlanGeometry",
    "Rulebook": "Rulebook",
}


@pytest.mark.parametrize(
    "name",
    ["RoomSpec", "Program", "SiteSpec", "Layout", "PlanGeometry", "Rulebook", "PolishExpression"],
)
def test_J03_schemas_validate(name: str, samples: dict[str, BaseModel]) -> None:
    inst = samples[name]
    if name in SCHEMA_FOR:
        path = export_schemas.SCHEMA_DIR / f"{SCHEMA_FOR[name]}.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
    else:  # PolishExpression has no exported schema file (RD §11); use the model schema
        schema = type(inst).model_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(json.loads(canonical_json(inst)))


def test_J03_taxonomy_schema() -> None:
    schema = json.loads(
        (export_schemas.SCHEMA_DIR / "Taxonomy.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(json.loads(canonical_json(load_taxonomy())))
    bad = json.loads(canonical_json(load_taxonomy()))
    bad["types"][0]["colour"] = "red"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(bad)


# --------------------------------------------------------------------------- J04


def test_J04_validate_cli(h: SimpleNamespace, tmp_path: Path) -> None:
    good = tmp_path / "rulebook.yaml"
    good.write_text(dump_yaml(h.make_rulebook()), encoding="utf-8")
    proc = h.run_module(["-m", "ale.contracts.validate", "rulebook", str(good)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0] == "OK"
    assert lines[1].startswith("info:")  # informational: taxonomy types absent from rulebook
    missing = lines[1].split(":", 1)[1].strip().split(", ")
    assert "stair" in missing
    assert "office" not in missing
    assert "circulation" not in missing

    data = yaml.safe_load(good.read_text(encoding="utf-8"))
    data["types"]["office"]["aspect"]["p10"] = None
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    proc = h.run_module(["-m", "ale.contracts.validate", "rulebook", str(bad)])
    assert proc.returncode == 1
    assert any(line.startswith("types.office.aspect.p10:") for line in proc.stdout.splitlines())


def test_J04_validate_in_process(
    h: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "program": h.make_program(),
        "site": h.make_site(),
        "layout": h.make_layout(),
        "plan": h.make_plan(),
        "taxonomy": load_taxonomy(),
        "rulebook": h.make_rulebook(),
    }
    for kind, model in files.items():
        path = tmp_path / f"{kind}.json"
        path.write_bytes(canonical_json(model))
        assert validate.main([kind, str(path)]) == 0
        assert capsys.readouterr().out.splitlines()[0] == "OK"
    yml = tmp_path / "program.yml"
    yml.write_text(dump_yaml(h.make_program()), encoding="utf-8")
    assert validate.main(["program", str(yml)]) == 0
    capsys.readouterr()

    code, lines = validate.validate_file("rulebook", tmp_path / "rulebook.json")
    assert code == 0
    assert lines[1].startswith("info:")

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"rooms": []}), encoding="utf-8")
    assert validate.main(["program", str(bad)]) == 1
    assert capsys.readouterr().out.startswith("rooms:")

    root_err = tmp_path / "root.json"
    root_err.write_text(json.dumps([1, 2]), encoding="utf-8")
    code, lines = validate.validate_file("program", root_err)
    assert code == 1
    assert lines[0].startswith("<root>:")

    code, lines = validate.validate_file("program", tmp_path / "missing.yaml")
    assert code == 1
    assert "cannot read" in lines[0]
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [1, 2\n", encoding="utf-8")
    code, lines = validate.validate_file("program", broken)
    assert code == 1


def test_J04_rulebook_all_types_present(h: SimpleNamespace, tmp_path: Path) -> None:
    rb = h.make_rulebook()
    tax = load_taxonomy()
    stats = rb.types["office"]
    needed = [t.key for t in tax.types if t.category.value in ("ROOM", "VERTICAL")]
    full = rb.model_copy(update={"types": dict.fromkeys(needed, stats)})
    path = tmp_path / "full.json"
    path.write_bytes(canonical_json(full))
    code, lines = validate.validate_file("rulebook", path)
    assert code == 0
    assert lines[1].endswith("(none)")


# --------------------------------------------------------------------------- J05


def test_J05_lock(h: SimpleNamespace, tmp_path: Path) -> None:
    root = h.copy_package(tmp_path)
    contracts = root / "ale" / "contracts"
    proc = h.run_module(["-m", "ale.contracts.lock"], pythonpath=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lock_file = contracts / "CONTRACTS.lock"
    text = lock_file.read_text(encoding="utf-8")
    rels = [line.split("  ", 1)[1] for line in text.splitlines()]
    assert rels == sorted(rels)
    assert "version.py" in rels
    assert "schemas/Rulebook.schema.json" in rels
    assert "CONTRACTS.lock" not in rels
    assert not any("__pycache__" in r for r in rels)
    proc = h.run_module(["-m", "ale.contracts.lock", "--check"], pythonpath=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    version = contracts / "version.py"
    version.write_text(version.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    proc = h.run_module(["-m", "ale.contracts.lock", "--check"], pythonpath=root)
    assert proc.returncode == 1
    assert "version.py" in proc.stdout


def test_J05_lock_in_process(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "pkg"
    (root / "sub").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / "a.py").write_text("A = 1\n", encoding="utf-8")
    (root / "sub" / "b.json").write_text("{}\n", encoding="utf-8")
    (root / "__pycache__" / "a.pyc").write_bytes(b"\0")
    assert lock.run(root, check=True) == 1  # no lock yet
    assert lock.run(root, check=False) == 0
    assert list(lock.parse_lock((root / lock.LOCK_NAME).read_text(encoding="utf-8"))) == [
        "a.py",
        "sub/b.json",
    ]
    assert lock.run(root, check=True) == 0
    (root / "a.py").write_text("A = 2\n", encoding="utf-8")
    (root / "c.txt").write_text("new\n", encoding="utf-8")
    (root / "sub" / "b.json").unlink()
    capsys.readouterr()
    assert lock.run(root, check=True) == 1
    out = capsys.readouterr().out
    assert "changed file: a.py" in out
    assert "unlocked file: c.txt" in out
    assert "missing file: sub/b.json" in out
    assert lock.parse_lock("\n") == {}
    # main() on the real package only checks (never writes); no lock is committed by 0.2.
    expected = 0 if (lock.PACKAGE_DIR / lock.LOCK_NAME).is_file() else 1
    assert lock.main(["--check"]) == expected


# --------------------------------------------------------------------------- J06


def test_J06_import_light(h: SimpleNamespace) -> None:
    code = (
        "import sys, time; t = time.perf_counter(); import ale.contracts.models; "
        "dt = time.perf_counter() - t; "
        "heavy = [m for m in ('numpy', 'networkx', 'pandas', 'torch') if m in sys.modules]; "
        "print(dt); print(','.join(heavy))"
    )
    proc = h.run_module(["-c", code])
    assert proc.returncode == 0, proc.stderr
    dt, heavy = proc.stdout.split("\n")[:2]
    assert float(dt) < 2.0
    assert heavy == ""


def test_version_and_layout_schema_version() -> None:
    assert CONTRACTS_VERSION == "1.6.0"  # superseded by Q.4 (D01), A.4 (A401), then G.1 (N01)
    assert Layout.model_fields["schema_version"].default == "ale.layout/1"
