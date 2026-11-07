"""Ticket 0.1 eval section 3: configuration (C01-C06)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from ale.config import ConfigError, load_config, parse_config, resolve_config_path
from ale.contracts import config as config_contract
from ale.contracts.config import AleConfig

# RD 0.1 section 6, verbatim.
EXPECTED_DEFAULTS: dict[str, dict[str, Any]] = {
    "workspace": {"format_version": 1},
    "grid": {"module_mm": 100},
    "area": {"tol_down_pct": 3.0, "tol_up_pct": 3.0, "tol_up_abs_m2": 1.2},
    "shape": {"aspect_max": 2.0},
    "circulation": {"ratio": 0.18, "min_door_edge_m": 1.2, "min_width_m": 1.2},
    "facade": {"min_facade_len_m": 2.4},
    "site": {"max_fill": 0.95},
    "determinism": {"seed": 42},
    "tools": {"oda_file_converter": "", "accoreconsole": "", "timeout_s": 300.0},
    "vlm": {
        "provider": "",
        "model_id": "",
        "api_key_env": "ALE_VLM_API_KEY",
        "temperature": 0.0,
        "prompt_version": "v1",
        "max_invalid_json_retries": 1,
        "timeout_s": 120.0,
    },
    "extract": {"raster_dpi": 300, "pdf_vector_min_paths": 200, "review_confidence": 0.6},
    "rulebook": {
        "min_support": 5,
        "blend_k": 10.0,
        "laplace_alpha": 1.0,
        "fidelity_weights": {"CAD": 1.0, "PDF_VECTOR": 0.8, "RASTER": 0.5},
    },
    "optimizer": {
        "max_iter": 200000,
        "time_budget_s": 120.0,
        "initial_acceptance": 0.8,
        "cooling": 0.95,
        "moves_per_temperature": 200,
        "weights": {
            "required_adjacency": 1000.0,
            "rulebook_adjacency": 1.0,
            "aspect": 1.0,
            "area_overshoot": 1.0,
            "facade_orientation": 1.0,
            "core_distance": 1.0,
            "circulation_length": 1.0,
        },
    },
    "logging": {"level": "INFO"},
}


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, dotted + "."))
        else:
            out[dotted] = value
    return out


EXPECTED_FLAT = flatten(EXPECTED_DEFAULTS)


@pytest.mark.parametrize(("key", "expected"), sorted(EXPECTED_FLAT.items()))
def test_C01_defaults(key: str, expected: Any) -> None:
    value: Any = AleConfig()
    for part in key.split("."):
        value = getattr(value, part)
    assert value == expected
    assert type(value) is type(expected)


def test_C01_defaults_complete() -> None:
    assert flatten(AleConfig().model_dump()) == EXPECTED_FLAT


def test_C02_partial_file(tmp_path: Path) -> None:
    path = tmp_path / "ale.toml"
    path.write_text("[grid]\nmodule_mm = 300\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.grid.module_mm == 300
    expected = dict(EXPECTED_FLAT, **{"grid.module_mm": 300})
    assert flatten(cfg.model_dump()) == expected


C03_CASES = [
    ("[grid]\nmodul_mm = 100\n", "ale.toml: grid.modul_mm:"),
    ("[vlm]\ntemperature = 0.2\n", "ale.toml: vlm.temperature:"),
    ("[circulation]\nratio = -0.1\n", "ale.toml: circulation.ratio:"),
    ("[grid]\nmodule_mm = 600.5\n", "ale.toml: grid.module_mm:"),
    ("[optimizer]\ncooling = 1.0\n", "ale.toml: optimizer.cooling:"),
    ("[shape]\naspect_max = 0.5\n", "ale.toml: shape.aspect_max:"),
    ("[workspace]\nformat_version = 2\n", "ale.toml: workspace.format_version:"),
    ("[vlm]\ntimeout_s = 0\n", "ale.toml: vlm.timeout_s:"),
    # Malformed TOML has no key: the line number takes its place.
    ("[grid]\nmodule_mm 100\n", "ale.toml: line 2, column"),
]


@pytest.mark.parametrize(("text", "prefix"), C03_CASES)
def test_C03_errors_named(invoke, make_ws, tmp_path: Path, text: str, prefix: str) -> None:
    ws = make_ws(tmp_path / "ws")
    (ws / "ale.toml").write_text(text, encoding="utf-8")
    result = invoke(["doctor", "--workspace", str(ws)])
    assert result.exit_code == 4
    lines = result.stderr.splitlines()
    assert any(line.startswith(prefix) for line in lines), result.stderr
    assert "Traceback" not in result.output


def test_C03_errors_named_one_line_per_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        parse_config("[grid]\nmodule_mm = 50\n[vlm]\ntemperature = 1.0\n[nope]\n")
    assert len(info.value.lines) == 3
    assert all(line.startswith("ale.toml: ") for line in info.value.lines)
    assert {line.split(":")[1].strip() for line in info.value.lines} == {
        "grid.module_mm",
        "vlm.temperature",
        "nope",
    }


def test_C03_errors_named_unreadable(tmp_path: Path) -> None:
    bad = tmp_path / "ale.toml"
    bad.write_bytes(b"[grid]\nmodule_mm = 100 # \xff\xfe\n")
    with pytest.raises(ConfigError) as info:
        load_config(bad)
    assert info.value.lines[0].startswith("ale.toml: encoding:")
    with pytest.raises(ConfigError) as info:
        load_config(tmp_path / "missing.toml")
    assert info.value.lines[0].startswith("ale.toml: file:")
    with pytest.raises(ConfigError) as info:
        parse_config('a = "unterminated')
    assert info.value.lines[0].startswith("ale.toml: ")


def _all_models(model: BaseModel) -> list[BaseModel]:
    models = [model]
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            models.extend(_all_models(value))
    return models


def test_C04_frozen() -> None:
    cfg = AleConfig()
    count = 0
    for model in _all_models(cfg):
        for name in type(model).model_fields:
            with pytest.raises(ValidationError):
                setattr(model, name, getattr(model, name))
            count += 1
    assert count == 44 + 16  # 44 keys + 14 tables + 2 nested tables


def test_C05_schema_no_drift() -> None:
    expected = json.dumps(AleConfig.model_json_schema(), indent=2, sort_keys=True) + "\n"
    committed = config_contract.schema_path().read_bytes()
    assert committed == expected.encode("utf-8")
    assert config_contract.schema_text() == expected


def test_C05_schema_no_drift_writer(tmp_path: Path) -> None:
    target = config_contract.write_schema(tmp_path / "schema.json")
    assert target.read_bytes() == config_contract.schema_path().read_bytes()
    # The documented regeneration command parses its flag (dry run: --help).
    proc = subprocess.run(
        [sys.executable, "-m", "ale.contracts.config", "--help"],
        capture_output=True,
        check=False,
        timeout=50,
    )
    assert proc.returncode == 0
    assert b"--write-schema" in proc.stdout


def test_C06_relative_paths_workspace(
    invoke, make_ws, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doctor_env: Path
) -> None:
    ws = make_ws(tmp_path / "ws")
    text = (ws / "ale.toml").read_text(encoding="utf-8")
    text = text.replace(
        'oda_file_converter = ""', 'oda_file_converter = "bin/ODAFileConverter.exe"'
    )
    (ws / "ale.toml").write_text(text, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "bin").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)

    cfg = load_config(ws / "ale.toml")
    resolved = resolve_config_path(ws, cfg.tools.oda_file_converter)
    assert resolved == ws / "bin" / "ODAFileConverter.exe"

    # A file in CWD/bin must NOT be picked up.
    (elsewhere / "bin" / "ODAFileConverter.exe").write_bytes(b"")
    result = invoke(["doctor", "--json", "--workspace", str(ws)])
    oda = next(c for c in json.loads(result.stdout)["checks"] if c["name"] == "ODA File Converter")
    assert oda["status"] == "missing"
    assert "configured path not found" in oda["detail"]

    # The file in <workspace>/bin is.
    (ws / "bin").mkdir()
    (ws / "bin" / "ODAFileConverter.exe").write_bytes(b"")
    result = invoke(["doctor", "--json", "--workspace", str(ws)])
    oda = next(c for c in json.loads(result.stdout)["checks"] if c["name"] == "ODA File Converter")
    assert oda["status"] == "found"
    assert Path(oda["detail"]) == ws / "bin" / "ODAFileConverter.exe"
