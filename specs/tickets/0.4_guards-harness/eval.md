# Ticket 0.4 — Guards & Test Harness · Evaluation

Every ID is a named pytest test. Expected numbers were computed by the Router.

## 0. Harness rules

pytest-timeout 60 s/test (from `pyproject.toml`); suite ≤ 90 s. No network. `CONTRACTS.lock --check` passes.
Process-tree tests marked POSIX-only are covered on Windows by the CI matrix (their Windows twins must exist and be marked `windows_only`).

## 1. Guards

| ID | Test | Pass condition |
|---|---|---|
| G01 | max_iter | `bounded(100, 60, label="t")` with a loop calling `tick()`: 100 ticks return `True`; the 101st raises `ConvergenceError(reason="max_iter", iterations=100)`. |
| G02 | time_budget | With `fake_clock`, `bounded(10**6, 5.0, clock=fake_clock)`, loop body `fake_clock.advance(1.0); budget.tick()`: tick 5 allowed (elapsed 5.0 is not > 5.0), tick 6 raises `reason="time_budget"` with `iterations == 5` and `elapsed_s == 6.0`. |
| G03 | snapshot | Snapshot callable called **exactly once**, only on exhaustion; its value is `state_snapshot`. A snapshot that raises `KeyError` still yields `ConvergenceError` with `snapshot_error` containing `KeyError`. |
| G04 | stop_mode | `list(bounded_range(7, 60, label="t", on_exhaust="stop")) == [0..6]`; with `bounded(..., on_exhaust="stop")` the 8th `tick()` returns `False`, `exhausted_reason == "max_iter"`, nothing raised, snapshot not called. |
| G05 | arg_validation | `max_iter` 0, −1, `True`, `1.5`; `time_budget_s` 0, −1, `inf`, `nan`; `label=""` → each raises `ValueError` or `TypeError`. |
| G06 | real_infinite_loop | `while True:` with `bounded(10**12, 0.2, label="inf")` and `tick()` → `ConvergenceError(reason="time_budget")` raised within 0.6 s of wall clock. |
| G07 | overhead | 10⁶ ticks complete in < 1.5 s on the CI runner (reported, gate on Linux only). |
| G08 | report | `to_report()` passes `json.dumps`; a 10 000-char snapshot repr is cut to 2 000 chars + `…[truncated]`; `ConvergenceError` with a picklable snapshot round-trips through `pickle`. |
| G09 | logging | Exhaustion emits exactly one `WARNING` on `ale.guards` containing the label and reason (caplog). |

## 2. External processes

All tools are `sys.executable -c "<code>"`, so the tests run anywhere.

| ID | Test | Pass condition |
|---|---|---|
| P01 | success_unicode | Child prints `é Ł 中` to stdout and `warn` to stderr → `ok`, `returncode == 0`, both captured exactly. |
| P02 | nonzero | Child `sys.exit(3)` → `returncode == 3`, `ok is False`, no exception. |
| P03 | timeout | Child sleeps 60 s, `timeout_s=0.5`, `kill_grace_s=0.5` → `timed_out`, `killed`, `duration_s < 2.5`. |
| P04 | tree_kill (POSIX; Windows twin) | Child starts a grandchild (sleep 60) and writes its PID to a file, then sleeps; after timeout the grandchild PID no longer exists within 3 s. |
| P05 | sigterm_ignored (POSIX) | Child ignores SIGTERM → still dead after `timeout_s + kill_grace_s + 1` s. |
| P06 | missing_exe | `run_tool(["definitely-not-a-tool-xyz"], timeout_s=5)` → `returncode is None`, `error` starts `executable not found`. |
| P07 | no_shell | argv `[sys.executable, "-c", "import sys; print(sys.argv[1])", "; echo HACKED"]` → stdout is exactly `; echo HACKED\n`. |
| P08 | big_output | Child writes 3 MiB to stdout and 3 MiB to stderr → finishes (no deadlock) within 10 s; each captured stream ≤ 1 MiB + marker and starts with `…[truncated]`. |
| P09 | env_merge | `env={"ALE_X": "1"}` → child sees `ALE_X == "1"` **and** inherited `PATH`. |
| P10 | input_text | `input_text="abc"` echoed back by the child. |
| P11 | bad_args | `timeout_s=0` and `argv=[]` → `ValueError`. |

## 3. Fixtures

| ID | Test | Pass condition |
|---|---|---|
| F01 | verbatim | Each `tests/fixtures/data/*.yaml` is byte-identical to `specs/tickets/0.4_guards-harness/fixtures/*.yaml` (6 files). |
| F02 | programs_valid | `program_8/25/60` load as `Program`; `len(instances())` = 8 / 25 / 60; Σ net area (target × quantity) = 75.0 / 334.0 / 962.0 m². |
| F03 | types_covered | Every type used ∈ {office, open_office, meeting_room, entrance_hall, reception, sanitary, sanitary_accessible, storage, technical_room, it_room, kitchenette, stair, lift}. |
| F04 | sites_valid | Sites load as `SiteSpec`; footprint areas 100.0 / 432.0 / 1224.0 m² (shapely); every coordinate converts with `m_to_modules(x, 100, EXACT)`; `site_L.north_angle_deg == 20.0`. |
| F05 | feasibility_intent | For each pair in `fixture_pairs`, with `default_config`: `Σnet × (1 + circulation.ratio) + 0.18 × n_instances ≤ footprint_area × site.max_fill`. Fill ratios (left / footprint) = 0.899, 0.923, 0.936 (±0.001). |
| F06 | tmp_workspace | `tmp_workspace` opens; its root path contains `ws é`; it is a different folder in two tests. |
| F07 | fake_clock | Starts at 1000.0; `advance(2.5)` → 1002.5. |

## 4. Static gates

| Gate | Threshold |
|---|---|
| `ruff check`, `ruff format --check`, `mypy` (strict) | clean |
| Coverage of `ale.guards` and `ale.proc` | ≥ 90 % line, ≥ 80 % branch (POSIX run) |
| Ownership | only RD §2 paths changed |
| Contracts | `python -m ale.contracts.lock --check` exits 0 |
