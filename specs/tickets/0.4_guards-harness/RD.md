# Ticket 0.4 — Guards & Test Harness · Requirements Document

> **Worker brief.** This file, `eval.md`, the `fixtures/` folder (same ticket folder), and the
> frozen contracts in `src/ale/contracts/` are your entire context. You may import
> `ale.contracts.*`, `ale.config`, `ale.workspace` and call `ale init`; do not modify them.

## 1. Purpose

Provide the runtime guards every later ticket must use, and the shared test harness:

1. `ale.guards` — bounded iteration with an iteration cap and a wall-clock budget, raising a
   diagnosable `ConvergenceError` instead of looping forever (or stopping cleanly, on request).
2. `ale.proc` — running external programs (ODA File Converter, AutoCAD `accoreconsole`) with a
   timeout, whole-process-tree kill, and a captured exit report. Never raises for a failed tool.
3. Shared fixtures — three programs (8, 25, 60 rooms) and three sites, exposed as pytest fixtures.

## 2. File ownership

```
src/ale/guards.py
src/ale/proc.py
tests/conftest.py                    # shared pytest fixtures (§5)
tests/fixtures/data/*.yaml           # verbatim copies of this ticket's fixtures/ folder
tests/fixtures/__init__.py           # load_program(name) / load_site(name) helpers
tests/guards/**                      # tests for this ticket
tests/harness/**                     # tests for this ticket
```

Do not modify `pyproject.toml`. If the harness needs a pytest setting, report it instead.

## 3. `ale.guards`

```python
class ConvergenceError(RuntimeError):
    label: str
    reason: Literal["max_iter", "time_budget"]
    iterations: int          # iterations COMPLETED before the guard tripped (== max_iter for "max_iter")
    elapsed_s: float
    state_snapshot: object | None
    snapshot_error: str | None   # repr of the exception raised by the snapshot callable, if any
    def to_report(self) -> dict[str, object]
        # JSON-serialisable: label, reason, iterations, elapsed_s (rounded to 3 decimals),
        # snapshot = repr(state_snapshot) truncated to 2000 characters (suffix "…[truncated]"), snapshot_error

class Budget:
    label: str; max_iter: int; time_budget_s: float
    iterations: int                        # completed iterations
    exhausted_reason: Literal["max_iter", "time_budget"] | None
    def tick(self) -> bool                 # call once per iteration (§semantics)
    def elapsed_s(self) -> float
    def remaining_s(self) -> float         # ≥ 0

@contextmanager
def bounded(max_iter: int, time_budget_s: float, *, label: str,
            snapshot: Callable[[], object] | None = None,
            on_exhaust: Literal["raise", "stop"] = "raise",
            clock: Callable[[], float] = time.monotonic) -> Iterator[Budget]

def bounded_range(max_iter: int, time_budget_s: float, *, label: str,
                  snapshot: Callable[[], object] | None = None,
                  on_exhaust: Literal["raise", "stop"] = "raise",
                  clock: Callable[[], float] = time.monotonic) -> Iterator[int]
    # yields 0, 1, 2, … ; equivalent to a `bounded` block whose loop calls tick() per item
```

**Semantics (frozen):**
- `tick()` is called at the start of each iteration. Let `k` = number of calls so far (including this one).
  If `k > max_iter` → exhausted with `"max_iter"`. Else if `clock() − start > time_budget_s` → exhausted
  with `"time_budget"`. Otherwise the tick is allowed: `iterations` becomes `k` and `tick()` returns `True`.
  Hence after `max_iter` allowed ticks `iterations == max_iter`, and the next tick exhausts the budget.
- On exhaustion: with `on_exhaust="raise"`, call `snapshot()` once (if given; an exception in it is caught
  and stored in `snapshot_error`), then raise `ConvergenceError`. With `"stop"`, set `exhausted_reason`,
  return `False` from `tick()`, and `bounded_range` stops yielding. No snapshot in stop mode.
- `start` is read on entering the context (or on the first `next()` of `bounded_range`).
- Arguments: `max_iter` an `int ≥ 1` (bool rejected); `time_budget_s` a finite float `> 0`; `label` non-empty.
  Invalid → `ValueError` / `TypeError`.
- Overhead: one `clock()` call per tick; no threads, no signals (must work identically on Windows).
- Log one `WARNING` on logger `ale.guards` when a budget is exhausted (label, reason, iterations, elapsed).

## 4. `ale.proc`

```python
@dataclass(frozen=True)
class ProcessReport:
    argv: tuple[str, ...]
    cwd: str | None
    returncode: int | None       # None if the process could not start or was killed before exiting normally
    timed_out: bool
    killed: bool                 # the runner had to kill the process tree
    duration_s: float
    stdout: str                  # decoded UTF-8 with errors="replace"; last 1 MiB kept, prefixed "…[truncated]\n" if cut
    stderr: str                  # same rule
    error: str | None            # e.g. "executable not found: ODAFileConverter"
    @property
    def ok(self) -> bool         # returncode == 0 and not timed_out and error is None
    def to_report(self) -> dict[str, object]   # JSON-serialisable

def run_tool(argv: Sequence[str | os.PathLike[str]], *, timeout_s: float,
             cwd: Path | None = None, env: Mapping[str, str] | None = None,
             input_text: str | None = None, kill_grace_s: float = 2.0) -> ProcessReport
```

- Never `shell=True`. Arguments passed as a list; a string like `"; echo x"` is a literal argument.
- `env=None` inherits the environment; a mapping is merged **over** `os.environ`.
- POSIX: start with `start_new_session=True`; on timeout send `SIGTERM` to the process group, wait
  `kill_grace_s`, then `SIGKILL` the group.
- Windows: `creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`; on timeout run
  `taskkill /T /F /PID <pid>` (resolved via `shutil.which("taskkill")`, never a literal path), then
  `proc.kill()` as fallback.
- Never raises for a failing tool: missing executable, permission denied, non-zero exit and timeout all
  return a `ProcessReport`. Only programming errors (`timeout_s ≤ 0`, empty argv) raise `ValueError`.
- Output is read concurrently (no deadlock on large outputs).
- Log one `INFO` line per call on `ale.proc` (argv[0] basename, returncode, duration, timed_out).

## 5. Shared fixtures (`tests/conftest.py`, `tests/fixtures/`)

Copy the six YAML files of this ticket's `fixtures/` folder **verbatim** to `tests/fixtures/data/`.

`tests/fixtures/__init__.py`:
```python
def load_program(name: Literal["program_08", "program_25", "program_60"]) -> Program
def load_site(name: Literal["site_rect_small", "site_rect", "site_L"]) -> SiteSpec
```
(using `ale.contracts.serialization.load_yaml`).

`tests/conftest.py` exposes these pytest fixtures (session scope unless stated):

| Fixture | Value |
|---|---|
| `program_8`, `program_25`, `program_60` | the loaded `Program`s |
| `site_rect_small`, `site_rect`, `site_l` | the loaded `SiteSpec`s |
| `fixture_pairs` | `(("program_08","site_rect_small"), ("program_25","site_rect"), ("program_60","site_L"))` |
| `taxonomy` | `load_taxonomy()` |
| `default_config` | `AleConfig()` |
| `tmp_workspace` (function scope) | a fresh workspace created by running `ale init` into `tmp_path / "ws é"`; returns the opened `Workspace` |
| `fake_clock` (function scope) | an object with `__call__() -> float` and `advance(seconds)`, starting at 1000.0 |

Plus a marker policy: register nothing new (markers live in `pyproject.toml`).

## 6. Out of scope

Any algorithm that uses the guards; ODA/accoreconsole specifics (Ticket 1.2); `pyproject.toml`.
