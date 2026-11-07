# Ticket 0.1 — Scaffolding & CLI · Evaluation

Every test ID below is a named pytest test (`test_S01_install_entrypoint`, …).
The Router re-runs the suite on a clean checkout before merging.

## 0. Harness rules

- `pytest-timeout` 60 s per test (from `pyproject.toml`); whole suite ≤ 120 s locally.
- CLI tests use `typer.testing.CliRunner` **and**, where marked (sub), a real subprocess
  `python -m ale …` (to exercise console encoding and exit codes).
- All filesystem work under `tmp_path`. No network.
- The "awkward path" fixture `AP = tmp_path / "Références" / "Plans 2024" / "ws ä"` is used wherever a path is involved.

## 1. Packaging & CLI surface

| ID | Test | Pass condition |
|---|---|---|
| S01 | install_entrypoint (sub) | `python -m ale --version` and `ale --version` print `0.1.0`, exit 0. |
| S02 | help_lists_all | `ale --help` output contains `init`, `doctor`, `ingest`, `extract`, `layers`, `review`, `rulebook`, `generate`, `status`; `ale rulebook --help` contains `build`. |
| S03 | stub_options | For every stub, `--help` lists every option of RD §5 (parametrised table in the test). |
| S04 | stub_exit_code | Each stub, given valid options and a valid workspace (and existing files for `--input/--program/--site/--rulebook`), exits **3** and stderr names the ticket id from RD §5. |
| S05 | option_validation | `ale ingest --input <missing dir>` → exit 2; `ale generate --variants 0` → exit 2; `ale rulebook build --min-support 0` → exit 2; `ale extract --kind foo` → exit 2. |
| S06 | workspace_env | With `ALE_WORKSPACE=AP` and no `--workspace`, `ale doctor` uses AP. With both, the flag wins. |

## 2. `ale init`

| ID | Test | Pass condition |
|---|---|---|
| I01 | exact_tree | `ale init --workspace AP` exits 0; the set of relative paths under AP equals exactly: `ale.toml, layer_map.yaml, corpus.sqlite, cache, cache/dxf, cache/raster, cache/vlm, extracted, rulebook, logs` (plus files inside `logs/` only). |
| I02 | corpus_db | `corpus.sqlite`: `PRAGMA user_version == 0`; table `ale_meta` has exactly keys `workspace_id` (valid UUID4), `created_at` (ISO-8601 UTC ending `Z`), `ale_version == "0.1.0"`, `format_version == "1"`. |
| I03 | template_config_valid | `ale.toml` written by init loads into `AleConfig`; `AleConfig()` (all defaults) equals the loaded config; every key in the file has a comment line directly above it. |
| I04 | idempotent | Run init twice. Second run exits 0 and prints `workspace already initialised`; SHA-256 of `ale.toml`, `layer_map.yaml`, `corpus.sqlite` unchanged; a deleted `cache/vlm/` is recreated. A user edit to `ale.toml` survives the second run. |
| I05 | refuses_foreign_dir | A non-empty folder containing `notes.txt` → exit 4; folder content unchanged (byte snapshot). |
| I06 | empty_existing_dir | Existing empty folder → initialised, exit 0. |
| I07 | awkward_paths (sub) | I01 + I04 pass using AP, invoked as a subprocess with both `/` and `\` separators on Windows (`windows_only` for the `\` variant). |

## 3. Configuration

| ID | Test | Pass condition |
|---|---|---|
| C01 | defaults | `AleConfig()` field values equal RD §6 exactly (table-driven, every key). |
| C02 | partial_file | An `ale.toml` containing only `[grid]\nmodule_mm = 300` loads; every other value is default. |
| C03 | errors_named | Each of these produces exit 4 and a stderr line starting `ale.toml: <key>:` — unknown key `[grid].modul_mm`; `vlm.temperature = 0.2`; `circulation.ratio = -0.1`; `grid.module_mm = 600.5`; `optimizer.cooling = 1.0`; `workspace.format_version = 2`; malformed TOML (line number reported). |
| C04 | frozen | Assigning to any `AleConfig` field raises `ValidationError`. |
| C05 | schema_no_drift | `AleConfig.model_json_schema()` serialised with `json.dumps(..., indent=2, sort_keys=True)` + `"\n"` equals the committed `config.schema.json` byte-for-byte. |
| C06 | relative_paths_workspace | `tools.oda_file_converter = "bin/ODAFileConverter.exe"` resolves to `<workspace>/bin/ODAFileConverter.exe` regardless of the process CWD (test changes CWD via `monkeypatch.chdir`). |

## 4. `ale doctor`

All doctor tests run with `PATH` reduced to the Python interpreter's folder and `ProgramFiles` unset/pointed at `tmp_path`, so the result does not depend on the test machine.

| ID | Test | Pass condition |
|---|---|---|
| D01 | clean_machine | Fresh workspace, no tools → exit 0; ODA and accoreconsole `missing` with install hint; VLM `disabled`. |
| D02 | json_shape | `--json` output parses; has `checks` (list of objects with exactly `name,status,required,detail`) and `ok == true`. |
| D03 | configured_tool | `tools.oda_file_converter` → a dummy file in tmp → `found` with that path. Configured path missing → `missing` with `configured path not found`. |
| D04 | env_and_path_detection | Dummy executable via `ALE_ODA_PATH` → found. Separately, dummy `ODAFileConverter` (exec bit set; `.exe` on Windows) on `PATH` → found. |
| D05 | programfiles_glob (`windows_only`) | Folders `ODA/ODAFileConverter 25.4.0/` and `ODA/ODAFileConverter 26.1.0/` with dummy exes under fake `ProgramFiles` → the 26.1.0 one is reported. |
| D06 | never_executes | Monkeypatch `subprocess.run`, `subprocess.Popen`, `os.system`, `os.startfile` (if present) to raise → D01–D04 still pass. |
| D07 | secret_hygiene | `vlm.provider = "x"`, env `ALE_VLM_API_KEY = "sk-TEST-SECRET-123"` → status `key present`; the string `sk-TEST-SECRET-123` does not appear in stdout, stderr, or any file under the workspace (log files included). |
| D08 | broken_workspace | Workspace whose `ale.toml` is invalid → exit 4. Read-only `cache/` (POSIX only, via chmod) → workspace check `fail`, exit 1. |
| D09 | no_network | D01 passes with `socket.socket.connect` monkeypatched to raise. |

## 5. Portability, encoding, logging

| ID | Test | Pass condition |
|---|---|---|
| P01 | cp1252_console (sub) | Run `ale init --workspace "<tmp>/Réf Łódź"` as a subprocess with `PYTHONIOENCODING=cp1252`: exit 0, no traceback in stderr (`Ł` is not encodable in cp1252 and must be replaced, not crash). |
| P02 | no_absolute_paths | `tests/test_no_absolute_paths.py` parses every `.py` under `src/ale` with `ast`, visits every string constant that is **not** a docstring, and fails on any match of `^(?:[A-Za-z]:[\\/]|\\\\[^\\]|/[A-Za-z0-9_.~-]|~[\\/])`. The test itself must catch a planted violation (unit-test the checker on a synthetic module). |
| P03 | utf8_io | `ale.toml` containing a comment `# Références` and `tools.oda_file_converter = "Outils/ODA été.exe"` loads on all OSes (CI matrix). |
| P04 | log_file | After `ale doctor --workspace AP`, `logs/ale-YYYYMMDD.log` exists; every line is valid JSON with keys `ts, level, logger, event, msg`. |
| P05 | ci_matrix | `.github/workflows/ci.yml` parses as YAML and declares the 3 OS × 3 Python matrix and the 4 steps of RD §12 (structural test). The Router additionally checks that the first CI run on the branch is green on all 9 jobs. |

## 6. Static gates

| Gate | Command | Threshold |
|---|---|---|
| Lint | `ruff check .` | 0 findings |
| Format | `ruff format --check .` | clean |
| Types | `mypy` (strict, from pyproject) | 0 errors |
| Coverage | `pytest --cov=ale --cov-branch` | ≥ 85 % line on files owned by this ticket |
| Ownership | `git diff --name-only <base>` | only paths listed in RD §3 |

## 7. Merge procedure

1. Worker returns its branch + `eval_report.md` in this folder (every ID: PASS/FAIL/SKIP with reason).
2. Router re-runs locally; any mismatch with the report → reject, logged in `notes.md`.
3. Router pushes; CI matrix must be green (P05).
4. Board → `DONE`.
