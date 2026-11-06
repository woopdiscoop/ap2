# Ticket 1.1 — Orchestrator Daemon · Evaluation Metrics

The Router merges Ticket 1.1 only when **every** gate below passes. Each test ID
must exist as a named pytest test (e.g. `test_E01_discovery_jpeg`) so results map
1:1 to this file.

## 0. Harness rules (Watchdog)

- `pytest-timeout` is active for the whole suite: default **30 s per test**; no test may raise its own limit above **60 s**.
- Whole suite wall-clock **≤ 120 s** on a 4-core machine.
- Tests run with tiny timings (e.g. `poll_interval_s=0.1`, `stability_checks=2`, `job_timeout_s=1.0`, `kill_grace_s=0.5`, `retry_backoff_s=[0,0,0]`) and an injected clock wherever time is asserted.
- Every test uses `tmp_path` for `watch_dir` and `workspace_dir`; nothing is written outside `tmp_path`.
- No network: tests must pass with networking disabled.
- Fixtures are **generated in code** (Pillow can write JPEGs and multi-page PDFs via `save_all=True`); no committed binary > 200 KB.
- Polling-based waits use a helper `wait_until(predicate, timeout_s)` — never a bare `sleep` followed by an assertion.

## 1. Functional tests

| ID | Name | Setup / action | Pass condition |
|----|------|----------------|----------------|
| E01 | discovery_jpeg | Daemon running; write `a.jpg` (800×600) into `watch_dir`. | Within `(stability_checks + 2) × poll_interval_s + 1 s`: exactly 1 document `RASTERIZED`, exactly 1 job `PENDING` with `job_id == f"{sha256[:16]}-p0000"`; `page_0000.png` exists, is RGB, 800×600. |
| E02 | discovery_pdf_multipage | Generate a 3-page PDF, A4 pages; `scan-once`. | 3 jobs, `page_index` 0,1,2. Each PNG has `width_px == round(595.28 × dpi / 72) ± 1` and same rule for height. `manifest.json` validates against the RD §9 shape and lists 3 pages with correct `sha256` of each PNG. |
| E03 | partial_write_gate | Write a 2 MB file in 8 chunks with a delay of `0.5 × poll_interval_s` between chunks, renamed from nothing (direct write to final name). | No document row exists while writing is in progress (assert after chunks 2, 4, 6). After the final chunk, exactly 1 document is ingested and its `doc_id` equals the SHA-256 of the **complete** content. |
| E04 | dedupe_same_content | Ingest `a.pdf`; then copy it to `sub/b.pdf`. | Still 1 row in `documents`; 2 rows in `document_paths`; job count unchanged; a `duplicate_content` log event emitted. |
| E05 | changed_content_same_path | Ingest `a.jpg`; overwrite with a different image; wait. | 2 documents (both retained), jobs exist for both, newest `doc_id` matches new content hash. |
| E06 | ignore_rules | Drop `.hidden.pdf`, `x.tmp`, `~$lock.pdf`, `plan.png`, `notes.txt`, `dir/.cache/c.pdf`. | Zero document rows. |
| E07 | startup_reconciliation | Place 5 valid files **before** starting the daemon. | All 5 ingested after startup with no filesystem events needed (run with observer disabled/mocked to prove the scan path). |
| E08 | lease_crash_recovery | Insert a job in `PROCESSING` with `attempts=1` and `lease_expires_at` in the past; start daemon with `noop`. | Job is recovered to `PENDING` (event `lease_recovered`), then processed to `DONE`, final `attempts == 2`. |
| E09 | timeout_kill | Processor `_test_sleep` (3600 s), `job_timeout_s=1.0`, `kill_grace_s=0.5`, `max_attempts=1`. | Job reaches `TIMEOUT` then `QUARANTINED` within 3 s of claim. Child PID is no longer alive (`os.kill(pid, 0)` raises `ProcessLookupError`) and is reaped (not a zombie). A second, `noop`-processable job queued afterwards still reaches `DONE`. |
| E10 | timeout_sigterm_ignored | Child installs `signal.signal(SIGTERM, SIG_IGN)` then sleeps. | Child is still killed (SIGKILL path) within `job_timeout_s + kill_grace_s + 1 s`. |
| E11 | retry_then_quarantine | Processor `_test_raise`, `max_attempts=3`, zero backoff. | Exactly 3 attempts recorded in `events`; final status `QUARANTINED`; `last_error` contains `RuntimeError` and `deliberate failure`; 3 attempt dirs exist; no `result/` dir. |
| E12 | nonretryable | `_test_raise` with `ALE_TEST_NONRETRYABLE=1`, `max_attempts=3`. | Status `QUARANTINED` after exactly **1** attempt. |
| E13 | backoff_respected | `_test_raise`, `retry_backoff_s=[10]`, injected clock. | Attempt 2 is not claimed before clock advances 10 s; is claimed after. |
| E14 | child_hard_crash | Test processor calls `os._exit(137)`. | Job `FAILED` (then retried per policy) with `last_error` containing `137`; daemon alive. |
| E15 | corrupt_inputs | Drop a truncated PDF, a `.jpg` containing random bytes, and an encrypted PDF. | 3 documents `FAILED` with non-empty `error`; zero jobs for them; daemon still ingests a valid file dropped afterwards. |
| E16 | oversize_guards | `max_file_bytes=1000` with a 2 KB JPEG; separately `max_image_pixels=10_000` with a 200×200 JPEG; `max_pdf_pages=2` with a 3-page PDF. | All three `FAILED` with a reason naming the guard; no crash. |
| E17 | exif_orientation | JPEG 400×200 with EXIF Orientation=6. | Raster PNG is 200×400. |
| E18 | requeue_cli | Quarantined job; run `requeue JOB_ID`. | Status `PENDING`, `attempts == 0`, event row written. `requeue` on a `DONE` job exits non-zero and changes nothing. |
| E19 | status_cli | After E11-like setup. | `status` prints valid JSON whose counts equal a direct `SELECT status, COUNT(*)` on the DB. |
| E20 | graceful_shutdown | `_test_sleep` job in flight; send SIGTERM to the daemon process (`run` subcommand in a subprocess). | Daemon exits with code 0 within `kill_grace_s + 2 s`; job is `PENDING`, `attempts` unchanged from its value while `PROCESSING`; no live child processes remain; `shutdown` event logged. |
| E21 | drain_cli | 4 valid files; `drain` with `noop`. | Process exits 0; 4+ jobs `DONE`; each has `result/result.json` and `result/noop.json`. |

## 2. Invariant & concurrency tests

| ID | Name | Pass condition |
|----|------|----------------|
| I01 | source_read_only | Snapshot `watch_dir` (every path, size, `mtime_ns`, SHA-256) before running E01–E06 + E15 in sequence and after. Snapshots are **identical**. |
| I02 | workspace_inside_watch | `workspace_dir` = `watch_dir/ws` → `ConfigError`; exit code 2 via CLI. |
| I03 | atomic_claim | 200 `PENDING` jobs; 8 threads, each with its **own** connection, claim in a loop until empty. Every job claimed **exactly once**; union = all 200; no `sqlite3.OperationalError` escapes. |
| I04 | state_machine_exhaustive | For every `(from, to)` pair in `JobStatus × JobStatus`: allowed pairs per RD §7 succeed; every other pair raises `InvalidTransition` and leaves the row unchanged. |
| I05 | idempotent_rescan | Run `scan-once` 3× on the same 5 files. Row counts in `documents`, `document_paths`, `jobs` identical after run 1, 2, 3. Raster files not rewritten (mtime unchanged). |
| I06 | determinism | Two fresh workspaces, same fixtures, same injected clock → identical `doc_id`s, `job_id`s, job claim order, and byte-identical PNGs and `manifest.json`. |
| I07 | events_audit | Every status change observed in tests E08–E14 has a matching `events` row with correct `from_status`/`to_status`. |
| I08 | config_validation | Unknown key, negative `poll_interval_s`, `stability_checks=0`, missing `watch_dir`, malformed `processor` string → each raises `ConfigError` with a message naming the key. |
| I09 | schema_migration | Fresh DB has `PRAGMA user_version == 1` and `journal_mode == wal`; opening an existing v1 DB is a no-op. |

## 3. Static & quality gates

| Gate | Command | Threshold |
|------|---------|-----------|
| Lint | `ruff check src tests` | 0 findings |
| Format | `ruff format --check src tests` | clean |
| Types | `mypy --strict src/ale/ingest/orchestrator` | 0 errors |
| Coverage | `pytest --cov=ale.ingest.orchestrator --cov-branch` | ≥ 85 % line, ≥ 75 % branch |
| No forbidden deps | `pip show pymupdf` / import scan | PyMuPDF (`fitz`) not imported anywhere |
| No busy loops | code review by Router | every `while` loop contains a sleep, a blocking wait, or a strict bound |

## 4. Merge procedure

1. Worker returns code on its own branch/worktree + a short `eval_report.md` in this folder listing every test ID with PASS/FAIL and the static-gate outputs.
2. Router re-runs the full suite independently. Any discrepancy with the Worker's report = reject.
3. Router updates `specs/tickets/board.md` → `DONE` and records the merge commit.
