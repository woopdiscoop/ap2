# Ticket 0.1: Scaffolding & CLI, Evaluation Report

Environment: Linux (container, uid 0), Python 3.13.18 (main run) and Python 3.11 (second run,
same result). Installed with `pip install -e ".[dev]"` into a fresh venv; typer 0.28.0,
pydantic 2.14.3, pytest 9.2.0, ruff 0.17.4, mypy 2.4.1. Windows and macOS were not available.

Totals: **123 passed, 0 failed, 3 skipped** (pytest node count, parametrised cases counted
separately). Suite wall time is about 5 s.

## 1. Test results by eval ID

| ID | Test(s) | Result |
|---|---|---|
| S01 | `test_S01_install_entrypoint` (subprocess: `python -m ale --version` and the `ale` console script) | PASS |
| S02 | `test_S02_help_lists_all` | PASS |
| S03 | `test_S03_stub_options` (9 parametrised commands) | PASS |
| S04 | `test_S04_stub_exit_code` (7 stubs: exit 3 plus the exact message with the ticket id) | PASS |
| S05 | `test_S05_option_validation` (the 4 eval cases plus 6 more of the same rule), `test_S05_option_validation_missing_workspace` | PASS |
| S06 | `test_S06_workspace_env` | PASS |
| I01 | `test_I01_exact_tree` (AP path) | PASS |
| I02 | `test_I02_corpus_db` | PASS |
| I03 | `test_I03_template_config_valid` (44 keys, each with a comment line directly above it) | PASS |
| I04 | `test_I04_idempotent` | PASS |
| I05 | `test_I05_refuses_foreign_dir`, `test_I05_refuses_foreign_dir_file_target` | PASS |
| I06 | `test_I06_empty_existing_dir` | PASS |
| I07 | `test_I07_awkward_paths[/]` (subprocess) | PASS |
| I07 | `test_I07_awkward_paths[\\]` | SKIP (`windows_only`: the backslash variant needs Windows) |
| C01 | `test_C01_defaults` (44 parametrised keys, value and type), `test_C01_defaults_complete` | PASS |
| C02 | `test_C02_partial_file` | PASS |
| C03 | `test_C03_errors_named` (8 cases through `ale doctor`, exit 4), `test_C03_errors_named_one_line_per_error`, `test_C03_errors_named_unreadable` | PASS |
| C04 | `test_C04_frozen` (all 60 fields of every model) | PASS |
| C05 | `test_C05_schema_no_drift`, `test_C05_schema_no_drift_writer` | PASS |
| C06 | `test_C06_relative_paths_workspace` (`monkeypatch.chdir`, including a decoy file under CWD/bin) | PASS |
| D01 | `test_D01_clean_machine` | PASS |
| D02 | `test_D02_json_shape` | PASS |
| D03 | `test_D03_configured_tool` | PASS |
| D04 | `test_D04_env_and_path_detection` | PASS |
| D05 | `test_D05_programfiles_glob` | SKIP (`windows_only`: ProgramFiles glob runs only on Windows) |
| D05 | `test_D05_programfiles_glob_logic_any_os` (same rule through `find_tool(is_windows=True)`) | PASS |
| D06 | `test_D06_never_executes` (also patches `subprocess.call` and `check_output`) | PASS |
| D07 | `test_D07_secret_hygiene` (`--log-level DEBUG`; checks stdout, stderr and every file under the workspace) | PASS |
| D08 | `test_D08_broken_workspace` (invalid `ale.toml`, exit 4), `test_D08_broken_workspace_variants` (5 other kinds of damage, exit 4) | PASS |
| D08 | `test_D08_broken_workspace_readonly_cache` (chmod) | SKIP (the container runs as root, and root ignores directory permissions. The non-root ubuntu and macOS CI runners will run it) |
| D08 | `test_D08_broken_workspace_unwritable_simulated` (`tempfile.mkstemp` raises for `cache/`: status `fail`, exit 1) | PASS |
| D09 | `test_D09_no_network` | PASS |
| P01 | `test_P01_cp1252_console` (subprocess, `PYTHONIOENCODING=cp1252`), `test_P01_cp1252_console_stub_message` | PASS |
| P02 | `test_P02_no_absolute_paths`, `test_P02_no_absolute_paths_checker_catches_planted_violation` | PASS |
| P03 | `test_P03_utf8_io` (also checks a UTF-8 BOM), `test_P03_utf8_io_path_helpers` | PASS |
| P04 | `test_P04_log_file`, `test_P04_log_file_formatter_and_levels`, `test_P04_log_level_from_config` | PASS |
| P05 | `test_P05_ci_matrix` (structural). The Router still has to check that the first CI run is green on all 9 jobs. | PASS (local structural part) |

## 2. Static gates

| Gate | Command | Result |
|---|---|---|
| Lint | `ruff check .` | `All checks passed!` |
| Format | `ruff format --check .` | `29 files already formatted` |
| Types | `mypy` (strict, `pydantic.mypy` plugin, `files = ["src/ale"]`) | `Success: no issues found in 21 source files` (Python 3.13 and 3.11) |
| Ownership | `git status` | only paths listed in RD §3, plus this report |
| Packaging | `pip wheel .` | the wheel contains `ale/templates/*`, `ale/contracts/config.schema.json` and the `ale` entry point |

## 3. Coverage (`pytest --cov=ale --cov-branch`)

Total is **97 %** (679 statements, 17 missed; 108 branches, 7 partial). Every file owned by
this ticket is at or above 88 %, with one exception: `__main__.py` (3 statements) shows 0 %
because it only runs in the subprocess tests, which coverage does not trace.

| File | Cover |
|---|---|
| cli/__init__.py | 88 % (the `--version` callback and `main()` run only in subprocess tests) |
| cli/commands/*.py | 100 % |
| config.py | 97 % |
| contracts/config.py | 94 % (the `--write-schema` argparse entry runs in a subprocess) |
| doctor.py | 98 % |
| logging_setup.py | 99 % |
| paths.py | 93 % |
| workspace.py | 100 % |

## 4. Spec issues, ambiguities and interpretations

1. **C03 malformed TOML.** A syntax error has no `<dotted.key>`. It is reported as
   `ale.toml: line <n>, column <m>: <message>`, so the line number takes the key's place. The test asserts
   that prefix.
2. **`ale generate --seed` "default from config".** `generate` has no `--workspace` option in
   RD §5, so there is no config to read the default from. The stub keeps `None`, and Ticket 3.x
   must decide where the config comes from.
3. **Stub `--workspace` is not marked required** in RD §5, yet stubs must open the workspace.
   I implemented it as optional (`ALE_WORKSPACE` env supported). If neither the flag nor the
   env var is given, the command fails with a usage error (exit 2, "no workspace given"),
   not exit 4.
4. **`vlm.timeout_s` has no range in RD §6.** Following the most literal reading, it is a plain
   float with no constraint, while `tools.timeout_s` is `> 0`. This probably should be `> 0` too.
   Changing it would alter the frozen schema, so it is left for the Router to decide.
5. **What counts as an existing workspace** (RD §7 "already an ALE workspace"): both `ale.toml`
   and `corpus.sqlite` must be present. A re-run creates **only missing folders**, as written.
   A missing `layer_map.yaml` is not recreated.
6. **Relative `ALE_ODA_PATH` / `ALE_ACCORECONSOLE_PATH` values** (RD §9 does not say how to
   resolve them) are resolved against the workspace folder, like config paths, and never
   against the CWD.
7. **The log file date** in `logs/ale-YYYYMMDD.log` is the UTC date, to match the UTC `ts` field.
8. **`ruff format --check .` also formats Markdown code blocks** in ruff 0.17. It would fail on
   `specs/tickets/0.2_contracts/RD.md`, a file this ticket does not own. `pyproject.toml` sets
   `[tool.ruff] extend-exclude = ["specs"]`. I did not read or change any file under `specs/`
   except this report.
9. **`--version`** prints the bare version (`0.1.0`).
10. **`ale init` messages** are `workspace created: <path>` and
    `workspace already initialised: <path>`. The second contains the required text.
11. **Doctor's "importable" check** does a real `importlib.import_module`, which is accurate but
    can take about a second when pandas or cv2 are installed. Missing tools carry the install
    hint in `detail`, because the JSON shape allows only `name,status,required,detail`.
12. **Windows-only behaviour** (the `\` separator in I07, the ProgramFiles glob in D05, a cp1252
    console) could not be run here. The D05 rule is also tested on every OS through
    `find_tool(..., is_windows=True)`.
13. **typer 0.28** vendors click, so the code does not import `click`. The test runner helper
    falls back to `CliRunner(mix_stderr=False)` for older typer/click (<8.2) installs.
