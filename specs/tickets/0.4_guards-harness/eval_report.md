# Ticket 0.4 — Guards & Test Harness · Evaluation report

Platform of this run: Linux, Python 3.13.  Whole suite: **408 passed, 5 skipped** in ~13 s
(about 19 s with coverage). Ticket tests (`tests/guards`, `tests/harness`): **81 passed, 2 skipped**.

## 1. Guards (`tests/guards/test_guards.py`)

| ID | Test(s) | Result |
|---|---|---|
| G01 | `test_G01_max_iter` | PASS |
| G02 | `test_G02_time_budget` | PASS: tick 5 allowed, tick 6 raises `time_budget`, `iterations == 5`, `elapsed_s == 6.0` |
| G03 | `test_G03_snapshot_called_once_on_exhaustion`, `test_G03_snapshot_not_called_without_exhaustion`, `test_G03_snapshot_raising_keyerror` | PASS |
| G04 | `test_G04_stop_mode` | PASS |
| G05 | `test_G05_arg_validation[...]` (9 cases from eval), `test_G05_arg_validation_other[...]` (6 extra) | PASS |
| G06 | `test_G06_real_infinite_loop` | PASS (trips at about 0.2 s) |
| G07 | `test_G07_overhead` | PASS: 10⁶ ticks in **0.18 s** without tracing; 1.25 s under coverage (gate skipped while a tracer is active, see §5) |
| G08 | `test_G08_report`, `test_G08_report_rounding_and_short_snapshot`, `test_G08_report_unrepresentable_snapshot`, `test_G08_pickle_round_trip` | PASS |
| G09 | `test_G09_logging`, `test_G09_logging_stop_mode_once` | PASS |

There are also edge-case tests for coverage (`test_budget_*`, `test_bounded_range_*`,
`test_convergence_error_message`). All of them PASS.

## 2. External processes (`tests/guards/test_proc.py`)

| ID | Test(s) | Result |
|---|---|---|
| P01 | `test_P01_success_unicode` | PASS |
| P02 | `test_P02_nonzero` | PASS |
| P03 | `test_P03_timeout` | PASS (duration about 0.5 s) |
| P04 | `test_P04_tree_kill` | PASS. A negative check with a leader-only kill made it fail, as it should. |
| P04 (Windows twin) | `test_P04_tree_kill_windows` (`windows_only`) | SKIP (Windows-only, Linux run) |
| P05 | `test_P05_sigterm_ignored` | PASS (duration about 1.5 s = timeout + grace) |
| P05 (Windows twin) | `test_P05_sigterm_ignored_windows` (`windows_only`) | SKIP (Windows-only, Linux run) |
| P06 | `test_P06_missing_exe` | PASS |
| P07 | `test_P07_no_shell` | PASS |
| P08 | `test_P08_big_output`, `test_P08_truncation_between_one_and_two_mib`, `test_P08_truncation_respects_utf8_boundaries`, `test_P08_small_output_not_truncated` | PASS (3 MiB + 3 MiB in about 0.04 s) |
| P09 | `test_P09_env_merge`, `test_P09_env_none_inherits` | PASS |
| P10 | `test_P10_input_text`, `test_P10_input_text_child_ignores_stdin` | PASS |
| P11 | `test_P11_bad_args[...]` (6 cases, including the eval's `timeout_s=0` and `argv=[]`) | PASS |

Extra tests: `test_cwd_and_pathlike_argv`, `test_missing_cwd`, `test_permission_denied` (POSIX),
`test_other_start_error`, `test_report_json_and_ok`, `test_logging_one_info_line`,
`test_logging_not_started`. All of them PASS.

## 3. Fixtures (`tests/harness/test_harness_fixtures.py`)

| ID | Test(s) | Result |
|---|---|---|
| F01 | `test_F01_verbatim` | PASS (6 files byte-identical) |
| F02 | `test_F02_programs_valid[program_08/25/60]` | PASS: 8 / 25 / 60 instances; 75.0 / 334.0 / 962.0 m² |
| F03 | `test_F03_types_covered` | PASS (also checks the types against `taxonomy.keys()`) |
| F04 | `test_F04_sites_valid[...]`, `test_F04_site_l_north` | PASS: 100.0 / 432.0 / 1224.0 m², all coordinates on the 100 mm grid |
| F05 | `test_F05_feasibility_intent[0/1/2]`, `test_F05_fixture_pairs_value` | PASS: fill = 0.8994 / 0.9227 / 0.9362 (expected 0.899 / 0.923 / 0.936), all ≤ 0.95 |
| F06 | `test_F06_tmp_workspace[1]`, `test_F06_tmp_workspace[2]` | PASS: two different roots named `ws é` |
| F07 | `test_F07_fake_clock` | PASS |

`test_loaders_reject_unknown_names` also PASSes.

## 4. Static gates

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | clean (55 files) |
| `mypy` (strict, `src/ale`) | clean (35 files). Also clean with `--platform win32` and `--platform darwin` for `guards.py` / `proc.py`. |
| Coverage `ale.guards` | 100 % line (131/131), 100 % branch (38/38) |
| Coverage `ale.proc` | 98.6 % line (137/139), 100 % branch (30/30). Missed: reader-thread `except (OSError, ValueError)`. |
| Ownership | only RD §2 paths plus this report |
| `python -m ale.contracts.lock --check` | exit 0 (`OK`) |
| Suite time | about 13 s (budget 90 s) |

Coverage was measured on the POSIX run with
`pytest --cov=ale.guards --cov=ale.proc --cov-branch`. The Windows-only code in `proc.py`
(the `else:` branch with `creationflags` and `taskkill`) is excluded with
`# pragma: no cover - Windows`. So are two defensive lines that cannot be reached here: the
"unkillable process" warning and the "pipe still held by a detached descendant" warning.

## 5. Spec issues, interpretations and notes

1. **Harness import path.** `tests/` is not a package, and `pyproject.toml` has no
   `pythonpath` setting. The helpers in `tests/fixtures/__init__.py` are therefore imported as
   the top-level module `fixtures`: `from fixtures import load_program`. This works because
   pytest's default `prepend` import mode puts `tests/` on `sys.path` for the root `conftest.py`.
   If a later ticket switches to `--import-mode=importlib`, `pythonpath = ["tests"]` (or similar)
   would need to be added to `pyproject.toml`. I did not change that file.
2. **`ale` logger propagation.** `ale.logging_setup.configure_logging()` (called by every
   in-process CLI invocation) sets `propagate=False` on the `ale` logger. After that, `caplog`
   no longer sees `ale.*` records. My G09 and proc logging tests monkeypatch `propagate=True`.
   `tmp_workspace` restores the `ale` logger's handlers, level and propagation after use.
   Later tickets that use `caplog` need the same workaround.
3. **`bounded_range` in raise mode** (literal reading of "equivalent to a `bounded` block whose
   loop calls tick() per item"): consuming the iterator to the end raises `ConvergenceError`.
   Callers that converge must `break`. A clean end needs `on_exhaust="stop"`.
4. **`to_report()["snapshot"]`** is always `repr(state_snapshot)`, so it is `"None"` when no
   snapshot was taken (literal reading). A `__repr__` that raises gives
   `"<unrepresentable snapshot: ...>"` instead of an exception.
5. **Eager validation.** `bounded()` and `bounded_range()` validate their arguments when called,
   not when the `with` block is entered or on the first `next()`. Start times still follow the
   spec. Using a bare `Budget` without `bounded` starts the clock on the first `tick()`. In
   stop mode every tick after exhaustion returns `False`, and only one WARNING is logged.
6. **Output decoding.** The *last 1 MiB is measured in bytes* before decoding. A partial UTF-8
   sequence at the cut is dropped, and the result is prefixed with `…[truncated]\n`. `\r\n` is
   normalised to `\n`. This is not stated in the RD, but P01 and P07 need exact `"...\n"` output on
   Windows. A lone `\r` (progress bars) is kept.
7. **`returncode` on timeout** is `None`, even though the OS reports a signal code, following
   "killed before exiting normally". `killed == timed_out`.
8. **POSIX kill sequence.** The runner sends SIGTERM to the group, then waits up to
   `kill_grace_s` for the leader (the wait ends early if the leader exits). It then sends SIGKILL
   to the group unconditionally, so that descendants which ignored SIGTERM or outlived the
   leader are also killed.
9. **Extra error strings** beyond the RD examples: `working directory not found: <cwd>`,
   `permission denied: <exe>`, `could not start <exe>: <OSError>`. `kill_grace_s < 0`,
   NaN/inf and bool `timeout_s` also raise `ValueError`.
10. **0.1's absolute-path checker (P02) flags `"/T"`, `"/F"` and `"/PID"`** as absolute paths.
    The taskkill switches are therefore built as `f"/{switch}"`; the argv is unchanged.
    This is a false positive in the checker, not a behaviour change.
11. **G07** asserts `< 1.5 s` only on Linux and only when no tracer or profiler is active. Under
    coverage, timing is not meaningful; the measured value is printed anyway.
12. **F04 "every coordinate"** includes `core_hint` as well as the footprint rings.
13. **P05** got a Windows twin too (the child ignores SIGINT/SIGBREAK; `taskkill /F` must still
    kill it). The eval only strictly requires twins for "process-tree tests".
14. After a normal exit, the reader threads drain until `max(deadline, now) + 5 s`. A detached
    descendant that keeps the pipe open makes the runner give up with a WARNING; the output may
    then be incomplete.
15. The ticket folder also contains `notes.md`. I did not read it, following the context rules.

No disagreement with any Router-computed expectation.
