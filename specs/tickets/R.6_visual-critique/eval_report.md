# Ticket R.6 · Evaluation report

Client mocked everywhere (`tests/critique/`); no network, no real key (a dummy value is put in a test-only env var).

| ID | Result | Tests |
|---|---|---|
| C601 | pass | `test_C601_request`, `test_C601_model_from_config` |
| C602 | pass | `test_C602_outputs`, `test_C602_no_defect` |
| C603 | pass | `test_C603_unknown_ids` |
| C604 | pass | `test_C604_advisory` |
| C605 | pass | `test_C605_cache`, `test_C605_cache_corrupt_entry_recalls` |
| C606 | pass | `test_C606_no_provider`, `test_C606_cli_exit_3` |
| C607 | pass | `test_C607_refusal_error[0-9]`, `test_C607_cli_exit_1`, `test_C607_unreadable_variant`, `test_C607_cli_success_and_json`, `test_C607_make_client`, `test_C607_fallback_block_text_only_final` |
| C608 | pass | `test_C608_render`, `test_C608_render_pixels`, `test_C608_cache_key_stable` |
| C609 | pass | `test_C609_gates` (lock check) + gate numbers below |

## Gates
- `ruff check .`: clean; `ruff format --check .`: clean.
- `mypy` (strict, `src`): no issues in 121 source files.
- Coverage `--cov=src/ale/critique`: 98 % (critic.py 98 %, render.py 98 %, `__init__` 100 %).
- `python -m ale.contracts.lock --check`: OK.
- Whole suite: 1254 passed, 11 skipped, 3 xfailed (pre-existing, none added) in 11 min 39 s.

## Spec issues
- RD §2 says "key missing → exit 3", but the shared CLI code 3 is `EXIT_NOT_IMPLEMENTED` for stubs. Followed the RD (exit 3, French message); the command defines its own `EXIT_NO_PROVIDER = 3`.
- RD §2 says the output is `{room_ids, kind, severity, observation, suggestion}` "plus summary" without saying that an unsupported provider (not `anthropic`) is also "provider missing"; treated as exit 3 with a French message.
- RD §2 does not say where the cache lives without `--workspace`: without a workspace, no cache is used (so no call is saved), and the default `AleConfig()` has no provider, hence exit 3.
- C603 "kept under « général »": implemented as an empty `room_ids` in the JSON and the text « général » in `critique.md`.
- C608 asks for label positions "inside its room rectangle" checked through returned label boxes; the render also returns circulation strips' boxes (labelled too), and checks cover them.
