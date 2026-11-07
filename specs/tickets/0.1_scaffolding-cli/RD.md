# Ticket 0.1 — Scaffolding & CLI · Requirements Document

> **Worker brief.** This file, `eval.md` (same folder) and the frozen contracts
> you are given are your entire context. Build exactly what is specified. The
> ticket is merged only when every test in `eval.md` passes, `ruff` and
> `mypy --strict` pass, and you have not modified any file you do not own (§3).

## 1. Purpose

Create the installable Python project `ale` (Architectural Layout Engine): packaging,
the `ale` command-line interface with **every** command as a typed stub, workspace
creation (`ale init`), configuration loading and validation (`ale.toml`), logging,
and the environment check `ale doctor`.

ALE is a **standalone workstation tool**: Windows first, macOS and Linux supported.
No daemon, no server, no network share, no hard-coded paths.

## 2. Environment

- Python **3.11, 3.12, 3.13** (stdlib `tomllib` is used for reading TOML).
- Runtime dependencies (core, always installed):
  `typer>=0.12`, `pydantic>=2.6,<3`, `PyYAML>=6.0`, `shapely>=2.0`, `networkx>=3.2`, `numpy>=1.26`, `jsonschema>=4.21`.
- Optional extras (declare now, empty implementations come later):
  `cad = ["ezdxf>=1.3"]`, `pdf = ["pymupdf>=1.24"]`, `raster = ["opencv-python-headless>=4.9", "Pillow>=10"]`,
  `excel = ["pandas>=2.1", "openpyxl>=3.1"]`, `vlm = []` (provider chosen later), `all = [...union...]`.
- Dev extra: `pytest>=8`, `pytest-timeout>=2.3`, `pytest-cov>=5`, `hypothesis>=6.100`, `ruff>=0.6`, `mypy>=1.10`, `types-PyYAML`.
- No network access at runtime or in tests.

## 3. File ownership

You **own** (create) these paths. Do not create or edit anything else.

```
pyproject.toml
README.md                                   # install + quick start (≤ 1 page)
.gitignore                                  # Python + workspace folders (ale_ws/, runs/)
.github/workflows/ci.yml
src/ale/__init__.py                         # __version__ = "0.1.0"
src/ale/__main__.py                         # python -m ale  ==  ale
src/ale/cli/__init__.py                     # typer app, command registration
src/ale/cli/commands/*.py                   # one module per command group
src/ale/workspace.py                        # create / open / validate a workspace
src/ale/config.py                           # load ale.toml → AleConfig, error formatting
src/ale/logging_setup.py
src/ale/doctor.py
src/ale/paths.py                            # path helpers (normalisation, display, relativisation)
src/ale/templates/ale.toml                  # template written by `ale init`
src/ale/templates/layer_map.yaml            # template written by `ale init`
src/ale/contracts/__init__.py               # EMPTY file (shared with Ticket 0.2, which also creates it empty)
src/ale/contracts/config.py                 # AleConfig pydantic model  ← frozen contract (§6)
src/ale/contracts/config.schema.json        # generated from AleConfig  ← frozen contract
tests/cli/**                                 # your tests
tests/test_no_absolute_paths.py
```

Ticket 0.2 creates the other files in `src/ale/contracts/` in parallel; Ticket 0.4
creates `tests/conftest.py` and `src/ale/guards.py`. Do not create those.

## 4. Packaging (`pyproject.toml`)

- Build backend `hatchling`, **src layout**, project name `ale`, console script `ale = "ale.cli:main"`.
- Include `src/ale/templates/*` and `src/ale/contracts/*.json|*.yaml` as package data.
- `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `timeout = 60`, `addopts = "-ra --strict-markers"`, markers: `slow`, `windows_only`, `needs_tool`.
- `[tool.ruff]`: `line-length = 100`, `target-version = "py311"`, rules `E,F,W,I,B,UP,SIM,PTH,RUF` (`PTH` enforces `pathlib`).
- `[tool.mypy]`: `strict = true`, `plugins = ["pydantic.mypy"]`, `files = ["src/ale"]`.
- `pip install -e ".[dev]"` must work on all three OSes.

## 5. CLI surface

Implemented with `typer`. `ale --help` lists every command below. Every option
listed must exist with the stated type, so later tickets only fill in the body.

| Command | Options (exact) | 0.1 behaviour |
|---|---|---|
| `ale init` | `--workspace PATH` (required) | **Implemented** (§7) |
| `ale doctor` | `--workspace PATH` (required), `--json` | **Implemented** (§9) |
| `ale ingest` | `--workspace PATH`, `--input PATH` (required, must be an existing directory), `--recursive/--no-recursive` (default recursive), `--include TEXT` (comma list, default `jpg,jpeg,png,tif,tiff,pdf,dwg,dxf`), `--meta PATH` (optional, must exist) | Stub |
| `ale extract` | `--workspace PATH`, `--only-new`, `--kind [dwg\|dxf\|pdf\|raster]` | Stub |
| `ale layers` | `--workspace PATH` | Stub |
| `ale review` | `--workspace PATH` | Stub |
| `ale rulebook build` | `--workspace PATH`, `--seed-rulebook PATH` (optional, must exist), `--min-support INT` (≥ 1) | Stub |
| `ale generate` | `--program PATH` (required, must exist, `.xlsx`), `--site PATH` (required, must exist, `.yaml/.yml`), `--rulebook PATH` (required, must exist), `--out PATH` (required), `--seed INT` (default from config), `--variants INT` (≥ 1, default 1) | Stub |
| `ale status` | `--workspace PATH`, `--json` | Stub |

Global options on the root app: `--log-level [DEBUG|INFO|WARNING|ERROR]` (default `INFO`), `--version`.

`--workspace` may also come from the env var `ALE_WORKSPACE`; the CLI flag wins.

**Stub behaviour:** after parsing and validating its options (and, where it takes
`--workspace`, opening and validating the workspace per §8), a stub prints
`ale <command>: not implemented yet (Ticket <id>)` to stderr and exits **3**.
Ticket ids: ingest 1.1, extract 1.2–1.4, layers 1.2, review 1.6, rulebook build 2.2,
generate 3.1–3.5, status 1.1.

**Exit codes (frozen):** `0` success · `1` runtime error · `2` usage error (typer default) ·
`3` not implemented · `4` invalid workspace or configuration.

## 6. Configuration contract (`src/ale/contracts/config.py`)

A pydantic v2 model tree, every model `model_config = ConfigDict(extra="forbid", frozen=True)`.
Field names below are the TOML keys. All values shown are defaults; values marked
**(open)** are placeholders pending a user decision — keep them exactly as given.

```toml
[workspace]
format_version = 1                      # int, == 1

[grid]
module_mm = 100                         # int, 100..1200; 1 module = module_mm millimetres (user decision U-1: 0.10 m)

[area]                                  # asymmetric surface tolerance
tol_down_pct   = 3.0                    # float 0..20
tol_up_pct     = 3.0                    # float 0..20
tol_up_abs_m2  = 1.2                    # float 0..10

[shape]
aspect_max = 2.0                        # float 1.0..6.0, HARD limit long side / short side for every room
                                        # (user decision U-2: 1:2 minimum, 2:1 maximum); circulation is exempt

[circulation]
ratio            = 0.18                 # float 0.05..0.5   (open)
min_door_edge_m  = 1.2                  # float > 0
min_width_m      = 1.2                  # float > 0, corridor clear width (user decision U-3)

[facade]
min_facade_len_m = 2.4                  # float > 0

[site]
max_fill = 0.95                         # float 0.5..1.0, feasibility check (Router-proposed)

[determinism]
seed = 42                               # int ≥ 0, default for `ale generate --seed`

[tools]
oda_file_converter = ""                 # str path; "" = auto-detect (§9)
accoreconsole      = ""                 # str path; "" = auto-detect (§9)
timeout_s          = 300.0              # float > 0, per external process call

[vlm]
provider       = ""                     # str (open); "" = VLM disabled
model_id       = ""                     # str (open)
api_key_env    = "ALE_VLM_API_KEY"      # name of the env var holding the key — never the key itself
temperature    = 0.0                    # float, MUST equal 0.0 (validator rejects anything else)
prompt_version = "v1"
max_invalid_json_retries = 1            # int 0..3
timeout_s      = 120.0

[extract]
raster_dpi           = 300              # int 72..1200
pdf_vector_min_paths = 200              # int ≥ 1  (N in the vector/scanned rule, Router-proposed)
review_confidence    = 0.6              # float 0..1, below → `ale review`

[rulebook]
min_support  = 5                        # int ≥ 1
blend_k      = 10.0                     # float > 0, seed pseudo-count (Router-proposed)
laplace_alpha = 1.0                     # float ≥ 0
[rulebook.fidelity_weights]
CAD        = 1.0                        # float 0..1
PDF_VECTOR = 0.8
RASTER     = 0.5

[optimizer]
max_iter              = 200000          # int ≥ 1
time_budget_s         = 120.0           # float > 0
initial_acceptance    = 0.8             # float 0..1 (T0 chosen so this share of uphill moves is accepted)
cooling               = 0.95            # float 0..1 exclusive
moves_per_temperature = 200             # int ≥ 1
[optimizer.weights]                     # all float ≥ 0
required_adjacency = 1000.0
rulebook_adjacency = 1.0
aspect             = 1.0
area_overshoot     = 1.0
facade_orientation = 1.0
core_distance      = 1.0
circulation_length = 1.0

[logging]
level = "INFO"                          # DEBUG|INFO|WARNING|ERROR
```

- Root model name: `AleConfig`; one sub-model per table (`GridConfig`, `AreaConfig`, …).
- Every table is optional in the file; missing tables/keys take the defaults above.
- Validation errors are reported as `ale.toml: <dotted.key>: <message>` (one line per error).
- `src/ale/contracts/config.schema.json` is generated with `AleConfig.model_json_schema()`
  by `python -m ale.contracts.config --write-schema` and committed. A test asserts it matches.
- Path-valued keys are stored as strings. Relative paths are resolved **against the workspace
  folder**, never against the current working directory.

## 7. `ale init --workspace PATH`

Creates exactly this tree (and nothing else):

```
<workspace>/
├── ale.toml               # copy of templates/ale.toml (all defaults, commented)
├── layer_map.yaml         # copy of templates/layer_map.yaml
├── corpus.sqlite          # empty SQLite DB: PRAGMA user_version = 0, one table ale_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
├── cache/dxf/  cache/raster/  cache/vlm/
├── extracted/
├── rulebook/
└── logs/
```

- `ale_meta` rows: `workspace_id` (UUID4), `created_at` (UTC ISO-8601 `…Z`), `ale_version`, `format_version = 1`.
- Target does not exist → create it (including parents). Target exists and is **empty** → initialise it.
  Target is already an ALE workspace → **idempotent**: create only missing folders, never
  overwrite `ale.toml`, `layer_map.yaml` or `corpus.sqlite`, print `workspace already initialised`, exit 0.
  Target is a non-empty folder that is not a workspace → exit 4, change nothing.
- `templates/ale.toml` must parse into `AleConfig` with all defaults and contain a comment line
  above every key explaining it (copy the comments of §6).
- `templates/layer_map.yaml`:
  ```yaml
  # Map CAD layer names to roles. Proposed by `ale layers`; edit and keep.
  # Roles: wall, door, window, room_label, area_label, zone, furniture, ignore
  version: 1
  layers: {}
  ```

## 8. Opening a workspace (`workspace.py`)

`open_workspace(path) -> Workspace` validates: folder exists, `ale.toml` parses into
`AleConfig`, `[workspace].format_version == 1`, `corpus.sqlite` opens and has `ale_meta`.
Failure → `WorkspaceError` (CLI exit 4) with a message naming the problem.
`Workspace` exposes `root`, `config: AleConfig`, and `path(*parts) -> Path` for every
sub-folder of §7. Nothing else.

## 9. `ale doctor --workspace PATH [--json]`

Reports, **without executing any external program and without any network access**:

| Check | Status values | Required? |
|---|---|---|
| Python version ≥ 3.11 | ok / fail | yes |
| Workspace opens (§8) and every folder is writable (create+delete a temp file) | ok / fail | yes |
| Optional extras importable: `ezdxf`, `fitz` (PyMuPDF), `cv2`, `PIL`, `pandas`, `openpyxl` | ok / missing | no |
| ODA File Converter | found (path) / missing | no |
| AutoCAD `accoreconsole` | found (path) / missing | no |
| VLM | disabled (provider "") / key present / key missing | no |

- **Tool detection order** (for each tool): (1) path in `ale.toml` if non-empty — must exist and be a file;
  (2) env var `ALE_ODA_PATH` / `ALE_ACCORECONSOLE_PATH`; (3) `shutil.which("ODAFileConverter")` /
  `shutil.which("accoreconsole")`; (4) Windows only: glob `%ProgramFiles%\ODA\ODAFileConverter*\ODAFileConverter.exe`
  and `%ProgramFiles%\Autodesk\AutoCAD *\accoreconsole.exe` built from `os.environ["ProgramFiles"]`
  (never a literal drive path); newest match by version number in the folder name wins.
  Never execute the found binary (the ODA converter opens a GUI when run without arguments).
- A configured path that does not exist → status `missing` with message `configured path not found: <path>`.
- VLM key check reads **only the presence** of the env var named by `vlm.api_key_env`.
  The key's value must never be printed, logged or written to disk.
- Missing optional items print an install hint (ODA: "install the free ODA File Converter and set
  [tools].oda_file_converter in ale.toml"; extras: `pip install "ale[cad]"`, etc.).
- Human output: a table. `--json`: `{"checks": [{"name", "status", "required", "detail"}], "ok": bool}`.
- Exit 0 if every *required* check is ok, else 1. Workspace that fails to open → exit 4.

## 10. Paths, encoding, portability

- Use `pathlib` everywhere (ruff `PTH`). Never `os.chdir`. Accept `D:/x`, `D:\x`, relative paths, `~`
  (expanded with `Path.expanduser`) and paths containing spaces and non-ASCII characters
  (`D:/Références/Plans 2024`).
- **No absolute path literals in `src/`** (enforced by `tests/test_no_absolute_paths.py`, §eval).
- At CLI start, call `sys.stdout.reconfigure(errors="replace")` and the same for stderr, so a
  Windows console using cp1252 never raises `UnicodeEncodeError`.
- Text files are read and written as UTF-8 explicitly (`encoding="utf-8"`), newline `"\n"`.
- `paths.display(p)` returns the path as given by the OS, NFC-normalised, for messages.

## 11. Logging (`logging_setup.py`)

- Console handler on stderr: human-readable, level from `--log-level` (or `[logging].level`).
- When a workspace is open: file handler `logs/ale-YYYYMMDD.log`, JSON lines
  (`ts`, `level`, `logger`, `event`, `msg`, plus extras), level DEBUG, UTF-8.
- One logger namespace `ale.*`. No `print` outside `ale.cli`.

## 12. CI (`.github/workflows/ci.yml`)

On push and pull_request: matrix `os: [windows-latest, macos-latest, ubuntu-latest]` ×
`python: ["3.11", "3.12", "3.13"]`; steps: `pip install -e ".[dev]"`, `ruff check .`,
`ruff format --check .`, `mypy`, `pytest --cov=ale --cov-report=term`. No secrets, no network
beyond `pip install`.

## 13. Out of scope

Any ingestion, extraction, rulebook or generation logic; the contracts of Ticket 0.2;
`ale.guards` and shared fixtures (Ticket 0.4); any VLM call.
