# ALE - Architectural Layout Engine

ALE is a standalone workstation tool (Windows first, macOS and Linux supported).
No daemon, no server, no network share.

## Install

Python 3.11, 3.12 or 3.13 is required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"          # development install
pip install -e ".[all]"          # optional extras: cad, pdf, raster, excel
```

## Quick start

```bash
ale init   --workspace "D:/Projets/ale_ws"   # create a workspace
ale doctor --workspace "D:/Projets/ale_ws"   # check the environment (no network, runs nothing)
ale --help                                   # list every command
```

`--workspace` can also be given through the `ALE_WORKSPACE` environment variable
(the command-line flag wins). `python -m ale` is equivalent to `ale`.

A workspace contains `ale.toml` (configuration, every key commented),
`layer_map.yaml`, `corpus.sqlite` and the folders `cache/`, `extracted/`,
`rulebook/` and `logs/`. Relative paths in `ale.toml` are resolved against the
workspace folder.

Exit codes: `0` success, `1` runtime error, `2` usage error, `3` not implemented,
`4` invalid workspace or configuration.

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest --cov=ale
```
