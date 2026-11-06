# Ticket 1.1 — Orchestrator Daemon · Requirements Document

> **Worker brief.** This document is self-contained. You do not need, and will
> not receive, any other project context. Build exactly what is specified here,
> nothing more. Your code is merged only if every gate in `eval.md` (same folder) passes.

## 1. Purpose

Build a long-running Python daemon that watches a directory (typically a NAS
mount) for new architectural floor-plan documents (PDF, JPEG), turns each into
normalized page rasters, and manages a **durable, crash-safe job queue** that
hands those rasters to a pluggable downstream processor (the first processor,
built in a later ticket, is a floor-plan vectorization model).

The daemon is also the **execution watchdog** for downstream processors: every
processor call runs in an isolated child process with a hard timeout. A
processor that hangs is killed, its job is marked `TIMEOUT`, and the daemon
keeps running.

## 2. Scope

**In scope**

- Directory monitoring (event-driven + periodic polling + startup reconciliation scan).
- File-stability gating (never ingest a file that is still being copied).
- Content-addressed de-duplication (SHA-256).
- Rasterization: PDF pages → PNG, JPEG → normalized PNG.
- SQLite-backed job queue with an explicit state machine, leases, retries, quarantine.
- Subprocess runner with hard timeout and kill.
- Processor plug-in interface + three reference processors used for testing.
- CLI and structured logging.

**Out of scope** (do not implement)

- Any machine-learning inference, vision API calls, or geometry processing.
- Any web UI, network service, or remote queue (Redis, Celery, etc.).
- Moving, renaming, or deleting files in the watched directory.

## 3. Environment & dependencies

- Python **3.11+** (uses stdlib `tomllib`).
- Runtime dependencies (pin minimum versions in `pyproject.toml`):
  - `watchdog>=4.0` — filesystem events and `PollingObserver`.
  - `pypdfium2>=4.25` — PDF rasterization. **Do not use PyMuPDF** (AGPL licence).
  - `Pillow>=10.0` — image decoding, EXIF orientation, PNG encoding.
- Stdlib only for: `sqlite3`, `hashlib`, `multiprocessing`, `logging`, `json`,
  `argparse`, `signal`, `pathlib`, `dataclasses`, `enum`.
- Dev dependencies: `pytest>=8`, `pytest-timeout`, `pytest-cov`, `ruff`, `mypy`.
- No network access at runtime or test time.

## 4. Package layout

Create exactly this layout (you may add private helper modules inside the package):

```
pyproject.toml                       # project "ale", src layout, deps above
src/ale/__init__.py
src/ale/ingest/__init__.py
src/ale/ingest/orchestrator/
    __init__.py
    __main__.py        # CLI entry: python -m ale.ingest.orchestrator
    config.py          # OrchestratorConfig dataclass + TOML loader + validation
    models.py          # enums, dataclasses: SourceDocument, Job, JobSpec, ProcessResult
    errors.py          # NonRetryableError, RasterizationError, ConfigError, InvalidTransition
    store.py           # SQLite schema, migrations, all queue operations
    stability.py       # file-stability tracker
    hashing.py         # streaming SHA-256
    rasterize.py       # PDF/JPEG → PNG pages + page manifest
    watcher.py         # watchdog observer wiring + reconciliation scan
    runner.py          # subprocess execution with timeout/kill
    processors.py      # Processor protocol, loader, reference processors
    daemon.py          # main loop, signal handling, graceful shutdown
tests/ingest/orchestrator/           # pytest suite (see eval.md)
tests/fixtures/                      # generated fixtures only (no binaries > 200 KB)
```

## 5. Configuration

Loaded from a TOML file passed via `--config`. Every key has the default shown.
Unknown keys or invalid values raise `ConfigError` at startup (fail fast).

```toml
[orchestrator]
watch_dir         = "/mnt/nas/plans"     # REQUIRED; must exist and be readable
workspace_dir     = "./var/ale"          # REQUIRED; created if missing; must NOT be inside watch_dir
db_path           = ""                   # default: <workspace_dir>/queue.sqlite3
recursive         = true
extensions        = [".pdf", ".jpg", ".jpeg"]   # case-insensitive match
ignore_globs      = [".*", "~$*", "*.tmp", "*.part", "*.crdownload", "Thumbs.db"]
use_polling       = true      # true = watchdog PollingObserver (required for SMB/NFS mounts)
poll_interval_s   = 5.0       # observer poll + stability check cadence
stability_checks  = 3         # consecutive identical (size, mtime_ns) observations required
rescan_interval_s = 300.0     # full reconciliation scan cadence (catches missed events)
raster_dpi        = 300       # PDF rasterization resolution
max_file_bytes    = 524288000 # 500 MB; larger files → document FAILED
max_pdf_pages     = 200
max_image_pixels  = 400000000 # Pillow decompression-bomb guard (per page)
processor         = "ale.ingest.orchestrator.processors:noop"   # "module:callable"
job_timeout_s     = 600.0     # hard wall-clock limit per job attempt
kill_grace_s      = 5.0       # SIGTERM → wait → SIGKILL
max_attempts      = 3
retry_backoff_s   = [30.0, 120.0, 600.0]  # delay before attempt 2, 3, ...
lease_s           = 0.0       # 0 → job_timeout_s + kill_grace_s + 30
workers           = 1         # concurrent processor child processes
log_format        = "json"    # "json" | "text"
log_level         = "INFO"
```

**Why polling is the default:** inotify/FSEvents do not report changes made by
*other machines* on SMB/NFS shares. `use_polling=false` is allowed for local disks only.

## 6. Data model (`models.py`)

```python
class DocStatus(StrEnum):  PENDING, RASTERIZED, FAILED
class JobStatus(StrEnum):  PENDING, PROCESSING, DONE, FAILED, TIMEOUT, QUARANTINED

@dataclass(frozen=True)
class SourceDocument:
    doc_id: str            # lowercase hex SHA-256 of file bytes
    media_type: str        # "application/pdf" | "image/jpeg"
    size_bytes: int
    page_count: int | None
    status: DocStatus
    first_seen_path: str   # path relative to watch_dir, POSIX separators
    discovered_at: str     # ISO-8601 UTC, e.g. "2026-11-06T10:15:00.123Z"
    error: str | None

@dataclass(frozen=True)
class Job:
    job_id: str            # f"{doc_id[:16]}-p{page_index:04d}"
    doc_id: str
    page_index: int        # 0-based
    raster_path: str       # absolute path to page PNG in workspace
    status: JobStatus
    attempts: int          # number of attempts STARTED
    not_before: str | None # ISO-8601 UTC; job not claimable before this time (backoff)
    lease_expires_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class JobSpec:             # the ONLY object passed to a processor (must be picklable)
    job_id: str
    doc_id: str
    page_index: int
    raster_path: str       # PNG, RGB, 8-bit
    page_manifest_path: str
    out_dir: str           # empty attempt directory the processor writes into
    attempt: int           # 1-based

@dataclass(frozen=True)
class ProcessResult:
    ok: bool
    outputs: list[str]     # paths relative to out_dir
    metrics: dict[str, float | int | str]
    message: str | None = None
```

## 7. Job state machine

Allowed transitions — **any other transition raises `InvalidTransition`** and
must be impossible through the public `store` API:

| From          | To            | Trigger |
|---------------|---------------|---------|
| *(new)*       | `PENDING`     | page rasterized successfully |
| `PENDING`     | `PROCESSING`  | atomic claim by a worker (`attempts += 1`, lease set) |
| `PROCESSING`  | `DONE`        | processor returned `ok=True` |
| `PROCESSING`  | `FAILED`      | processor raised / returned `ok=False` / child crashed |
| `PROCESSING`  | `TIMEOUT`     | wall clock exceeded `job_timeout_s` |
| `PROCESSING`  | `PENDING`     | lease expired (crash recovery) or graceful-shutdown requeue — `attempts` NOT decremented |
| `FAILED`      | `PENDING`     | automatic retry if `attempts < max_attempts` (sets `not_before`) |
| `TIMEOUT`     | `PENDING`     | automatic retry if `attempts < max_attempts` (sets `not_before`) |
| `FAILED`/`TIMEOUT` | `QUARANTINED` | `attempts >= max_attempts`, **or** the error was a `NonRetryableError` |
| `QUARANTINED` | `PENDING`     | manual `requeue` CLI command only (resets `attempts` to 0) |

`DONE` is terminal. Every transition writes one row to the `events` table.

## 8. SQLite store (`store.py`)

- Open with `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`.
- Schema version tracked in `PRAGMA user_version`; provide migration from 0 → 1.
- Tables (minimum columns; add indexes on `jobs(status, not_before, created_at)`):

```sql
documents(doc_id TEXT PRIMARY KEY, media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
          page_count INTEGER, status TEXT NOT NULL, first_seen_path TEXT NOT NULL,
          discovered_at TEXT NOT NULL, error TEXT)
document_paths(doc_id TEXT NOT NULL REFERENCES documents, rel_path TEXT NOT NULL,
               size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, seen_at TEXT NOT NULL,
               PRIMARY KEY (doc_id, rel_path))
jobs(job_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents, page_index INTEGER NOT NULL,
     raster_path TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
     not_before TEXT, lease_expires_at TEXT, last_error TEXT,
     created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(doc_id, page_index))
events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, job_id TEXT, doc_id TEXT,
       from_status TEXT, to_status TEXT, detail TEXT)
```

- **Atomic claim:** a single `UPDATE … SET status='PROCESSING' … WHERE job_id = (SELECT job_id FROM jobs WHERE status='PENDING' AND (not_before IS NULL OR not_before <= :now) ORDER BY created_at, job_id LIMIT 1) RETURNING *` inside `BEGIN IMMEDIATE`. Two concurrent claimers must never receive the same job.
- **Lease recovery:** on startup and every `poll_interval_s`, jobs in `PROCESSING` with `lease_expires_at < now` go back to `PENDING`.
- A path-level lookup `(rel_path, size_bytes, mtime_ns)` lets the scanner skip hashing files it has already seen unchanged.
- All timestamps UTC ISO-8601 with millisecond precision and a `Z` suffix. Inject a clock (`Callable[[], datetime]`) so tests can control time.

## 9. Discovery pipeline

For every candidate path (from a watchdog event **or** a reconciliation scan):

1. **Filter.** Extension in `extensions` (case-insensitive); no path component matches `ignore_globs`; is a regular file (not a symlink pointing outside `watch_dir`).
2. **Stability gate (`stability.py`).** Record `(size_bytes, mtime_ns)` on each poll. The file becomes *stable* after `stability_checks` consecutive identical observations **and** a successful open-for-read of the first and last 4 KiB. Any change resets the counter. Files that disappear are dropped from tracking.
3. **Skip known.** If `(rel_path, size_bytes, mtime_ns)` is already in `document_paths`, stop.
4. **Hash.** Streaming SHA-256 in 1 MiB chunks. If `doc_id` already exists → insert a `document_paths` alias row, log `duplicate_content`, stop (no new jobs).
5. **Guard.** `size_bytes > max_file_bytes` → document `FAILED` with reason, stop.
6. **Rasterize (`rasterize.py`).** Write to `<workspace>/raster/<doc_id>/`:
   - PDF: each page rendered with pypdfium2 at `raster_dpi` → `page_0000.png`, … Honour the page `/Rotate` value. `page_count > max_pdf_pages` → `FAILED`.
   - JPEG: apply EXIF orientation (`ImageOps.exif_transpose`), convert to RGB 8-bit → `page_0000.png`.
   - Write PNGs to a temp name then `os.replace` (atomic). Re-rasterizing an existing `doc_id` must be a no-op.
   - Write `manifest.json` (one per document):
     ```json
     {"doc_id": "...", "media_type": "application/pdf", "raster_dpi": 300,
      "pages": [{"page_index": 0, "file": "page_0000.png", "width_px": 4961, "height_px": 3508,
                 "source_width_pt": 1190.55, "source_height_pt": 841.89, "rotation_deg": 0,
                 "source_dpi": null, "sha256": "..."}]}
     ```
     For JPEG: `source_*_pt` = null, `source_dpi` = EXIF/JFIF DPI if present else null, `raster_dpi` = null.
   - Any decode error, encrypted PDF, or decompression-bomb trip → `RasterizationError` → document `FAILED`, error stored, daemon continues.
7. **Enqueue.** In one transaction: document → `RASTERIZED`, one `PENDING` job per page.

**Invariant — read-only source:** the daemon never creates, modifies, renames, or
deletes anything under `watch_dir`. Open source files with mode `"rb"` only.
`workspace_dir` inside `watch_dir` is a `ConfigError`.

## 10. Processor interface (`processors.py`)

```python
class Processor(Protocol):
    def __call__(self, spec: JobSpec) -> ProcessResult: ...
```

- Loaded from the `processor` config string `"package.module:callable"` **inside the child process** (so heavy imports like ML frameworks never load in the daemon).
- A processor signals a permanent failure by raising `ale.ingest.orchestrator.errors.NonRetryableError` (→ job goes straight to `QUARANTINED`). Any other exception is retryable.
- Reference processors (required, used by tests and as examples):
  - `noop` — writes `noop.json` containing the `JobSpec` as JSON; returns `ok=True`.
  - `_test_sleep` — sleeps `float(os.environ.get("ALE_TEST_SLEEP_S", "3600"))` seconds.
  - `_test_raise` — raises `RuntimeError("deliberate failure")`; if env `ALE_TEST_NONRETRYABLE=1`, raises `NonRetryableError` instead.

## 11. Runner / execution watchdog (`runner.py`)

- Each attempt: create `<workspace>/jobs/<job_id>/attempt_<n>/` (empty), build `JobSpec`, start a child via `multiprocessing.get_context("spawn")`.
- Child loads the processor, calls it, sends back the `ProcessResult` (or a serialized exception: type name, message, traceback, `non_retryable` flag) through a `Pipe`.
- Parent waits up to `job_timeout_s`. On overrun: `terminate()` (SIGTERM), wait `kill_grace_s`, then `kill()` (SIGKILL), then `join()`. Job → `TIMEOUT`. The runner must guarantee the child is reaped (no zombies, no orphans).
- Child exits without sending a result (segfault, `os._exit`, OOM kill) → `FAILED` with exit code in `last_error`.
- On `DONE`: write `result.json` (the `ProcessResult` + timings) into the attempt dir, then atomically `os.replace` the attempt dir to `<workspace>/jobs/<job_id>/result/`. Failed attempt dirs are kept for debugging.
- Record per-attempt metrics in the `events.detail` JSON: `wall_s`, `exit_code`, `outcome`.

## 12. Daemon loop (`daemon.py`)

- Startup: load config → open store (migrate) → recover expired leases → reconciliation scan of `watch_dir` → start observer → enter loop.
- Loop (every `poll_interval_s`): advance stability tracker; ingest newly stable files; recover leases; promote eligible `FAILED`/`TIMEOUT` jobs (retry or quarantine); fill free worker slots with claimed jobs; reap finished runners; every `rescan_interval_s` run a reconciliation scan.
- **Graceful shutdown** on SIGINT/SIGTERM: stop the observer, stop claiming, give in-flight jobs up to `kill_grace_s` to finish, then kill them and return them to `PENDING` (no attempt increment), close the DB, exit code 0.
- A failure in one file or one job must never terminate the daemon. Only `ConfigError` and an unopenable database are fatal (exit code 2).

## 13. CLI (`__main__.py`)

```
python -m ale.ingest.orchestrator --config CONFIG run          # start daemon (foreground)
python -m ale.ingest.orchestrator --config CONFIG scan-once    # one reconciliation + ingest pass; no processing; exits
python -m ale.ingest.orchestrator --config CONFIG drain        # scan-once, then process until no claimable jobs remain; exits
python -m ale.ingest.orchestrator --config CONFIG status       # JSON: counts per DocStatus / JobStatus
python -m ale.ingest.orchestrator --config CONFIG requeue JOB_ID   # QUARANTINED → PENDING
```

`scan-once` must treat files as stable if they pass a single size/mtime check
spaced `poll_interval_s` apart (so it terminates).

## 14. Logging

- `log_format="json"`: one JSON object per line on stderr with keys `ts`, `level`, `event`, plus context (`doc_id`, `job_id`, `rel_path`, …).
- Required `event` names: `file_detected`, `file_stable`, `duplicate_content`, `document_failed`, `document_rasterized`, `job_claimed`, `job_done`, `job_failed`, `job_timeout`, `job_quarantined`, `lease_recovered`, `shutdown`.

## 15. Non-functional requirements

- **Determinism:** given the same files and clock, the same `doc_id`s, `job_id`s, raster bytes, and job order are produced.
- **Bounded loops:** every loop is bounded or driven by a timer; no busy-waiting (the main loop must sleep between iterations).
- **Typing:** `mypy --strict` clean for `src/ale/ingest/orchestrator`.
- **Style:** `ruff check` and `ruff format --check` clean.
- **Portability:** Linux is the target; must not crash on macOS. Windows is not required.

## 16. Deliverables

1. Source under `src/ale/ingest/orchestrator/` as laid out above.
2. Tests under `tests/ingest/orchestrator/` implementing every case in `eval.md`.
3. `pyproject.toml` with dependencies, pytest config (`timeout = 30` default), and ruff/mypy config.
4. `src/ale/ingest/orchestrator/README.md` (≤ 1 page): how to configure and run, including the NAS polling note.
5. An example config at `examples/orchestrator.toml`.
