# Ticket Q.4: evaluation report

Environment: Linux, Python 3.13, venv inside the worktree (`.venv`, `pip install -e
".[dev,excel,cad,pdf,raster,vlm]"`). Base: `origin/claude/new-session-2hmd3s` at `12b59b0`
(Q.3 merged). Contracts go to **1.4.0**; `python -m ale.contracts.lock --check` reports OK.

**Status:** every eval ID D01–D07 has a test named after it. D01, D02, D03, D04, D06 and D07
pass. **D05 fails on `NO_FACADE ≤ 1`**: the AREP floor ends with `FACADE_DEPTH = 0` (met) and
`NO_FACADE = 3`. The test is kept as written (no xfail); §3 explains why ≤ 1 is out of reach of
the current grammar and optimiser in practice.

## 1. What changed

### Contracts 1.4.0 (amendment, done as A.3 did it)
- `CONTRACTS_VERSION = "1.4.0"`.
- `FacadeConfig.max_depth_m: float | None = None` (`gt=0`; `None` = rule off, the default). Its
  description names the through-room doubling and the `FACADE_DEPTH` code.
- `config.schema.json` regenerated, `CONTRACTS.lock` regenerated. The other schemas are
  unchanged (`export_schemas --check` OK).
- Contract tests: version asserts updated, K02 now allows exactly `config.py` and
  `config.schema.json` to differ from 1.0.0, new `test_contracts_q4.py` (D01).
- Violation codes are not enumerated in the contracts package (`Violation.code` is a free
  string), so `FACADE_DEPTH` lives in `ale.geometry.evaluate` and in both `HARD_CODES` sets
  (`ale.optimize.anneal`, `ale.topology.seed`).

### Geometry
- `Consts.dmax = floor(max_depth_m · 1000 / module_mm)` (exact, `None` when off).
  `RoomReq.deep`: `needs_facade` and `T > amax · dmax²` (§4 of the RD writes `2 · Dmax²` for
  `amax = 2`).
- **Evaluator** (`evaluate.py`): for a `needs_facade` room with façade (exterior contact `≥ f`,
  so a room never gets both `NO_FACADE` and `FACADE_DEPTH`), `facade_depth(rect, poly)` gives its
  extent perpendicular to its longest exterior contact (ties: the smaller depth) and whether
  it also touches the exterior on the opposite side. `FACADE_DEPTH` (hard) when depth > `dmax`,
  or > `2 · dmax` for a through room. A deep room's aspect above `amax` is reported as
  **`ASPECT_DEPTH`** (soft: not in `HARD_CODES`) instead of `ASPECT`. `FACADE_CODES =
  {NO_FACADE, FACADE_DEPTH}` is exported for the façade pulls.
- **Checks**: invariant 6 accepts `ASPECT` or `ASPECT_DEPTH`.
- **Solver / realiser** (`blocks.py`): a predicted `FACADE_DEPTH` (a `needs_facade` room bay
  with façade in a block deeper than `dmax`, or a lit outermost stack room taller than `dmax`)
  adds one to `BlockOut.no_facade`, i.e. the Q.3 key position (`n_failures, n_no_facade, …`) of
  the depth search and band descent; `fastreal` inherits it through the shared solver. A deep
  room with no compliant width at a depth `≤ dmax` takes `Solver.deep_width` (area rule and
  `wmin` only; the narrow façade width in exterior blocks), so "depth wins".
- With the rule off every new branch is skipped: same keys, widths and violations.

### Topology / optimise
- Seed assignment (`depth.py`, `_depth_penalty`): a `needs_facade` room that would be a room
  bay of an outer block deeper than `dmax` pays the same penalty as one in an inner block, so it
  goes to an exterior block whose depth fits.
- Seeder façade pull (`seed.py`), annealer G9 focus (`anneal.focus_on`) and the polish façade
  neighbourhood treat `FACADE_DEPTH` like `NO_FACADE` (`FACADE_CODES`).

### Report (`export/report.py`)
- With the rule on, the summary states "Profondeur max. depuis la façade : 7,20 m (double pour
  une pièce traversante)".
- A section **"Proportion > 2 imposée par la règle de profondeur"** (the value is
  `shape.aspect_max`) lists the `ASPECT_DEPTH` rooms with their dimensions and proportion,
  and says they are not counted as hard. It only appears when such a room exists, so the
  3.5 section list is unchanged otherwise.

## 2. Eval IDs
| ID | Test | Result |
|---|---|---|
| D01 | `tests/contracts/test_contracts_q4.py::test_D01_contract` | pass: 1.4.0, default `None`, old TOML loads unchanged, validation (`> 0`, `extra="forbid"`), schema regenerated and in sync, `export_schemas --check` and `lock --check` OK |
| D02 | `tests/optimize/test_optimize_q4.py::test_D02_off_by_default` | pass: SHA-256 of the canonical start and final layouts of the P8/P25/P60 quality runs (seed-3 start, 50 attempts, anneal seed 6, 1 500 / 1 500 / 1 100 iterations) equal the digests computed with the pre-Q.4 code (`12b59b0`); an explicit `max_depth_m = None` realises byte-identically |
| D03 | `tests/geometry/test_geometry_q4.py::test_D03_violation` (+ `_depth_from_longest_contact`, `_realised_deep_office`) | pass: 9.6 m-deep office, max 7.2 → one `FACADE_DEPTH` ("depth 16 > 12"); at exactly 12 modules none; a 12 m through room → none (limit 24), 15 m → one; module 600: `dmax = 12` (and 7.5 m → 12, floor) |
| D04 | `test_D04_big_room` (+ solver, block-count, rule-off tests; `tests/export/test_export_q4.py`) | pass: the 160 m² `needs_facade` room is realised 38 × 12 modules (22,8 × 7,2 m, depth 7.2 m, 456 cells within 445–488), `ASPECT_DEPTH` reported, no `ASPECT`/`FACADE_DEPTH`, `n_hard = 0`, `check_layout == ()`; the report lists it |
| D05 | `tests/optimize/test_optimize_q4.py::test_D05_arep_floor` | **fail**: `FACADE_DEPTH` 0 (≤ 0 met), `NO_FACADE` **3** (target ≤ 1) — see §3 |
| D06 | `test_D06_no_regression`; Q301–Q304 unchanged | pass: identical layouts (D02), so Q301 (P60 `NO_FACADE` 6), Q302 (P8 0, P25 5, P60 9), Q303 (P25 7 → 5), Q304 (P8 seeds 1–5) hold as in Q.3 |
| D07 | `test_D07_gates` and the gate runs of §4 | see §4 |

## 3. D05: the AREP-MS floor
Programme rebuilt in the test: 16 lines, 25 rooms, 649 m²; bar 54 × 15.6 m = 90 × 26 modules;
module 600 (`s = c = 2`, `f = 4`, `dmax = 12`); area 0 / +10 % / 0; aspect ≤ 2.
Budgets: seed 3 with `max_attempts = 50`, anneal seed 6 with `max_iter = 1 500` (Q.3 convention).

| Run | start (hard by code) | final (hard by code) | soft |
|---|---|---|---|
| rule on (D05, seed 3) | NO_FACADE 3, REQUIRED_ADJ 1 | **NO_FACADE 3** (FACADE_DEPTH 0) | ASPECT_DEPTH 1 (Président 22,8 × 7,2 m) |
| rule on, seed 5 (exploration) | NO_FACADE 2, REQUIRED_ADJ 1 | NO_FACADE 2, REQUIRED_ADJ 1 | ASPECT_DEPTH 1 |
| rule off, seed 3 (exploration) | NO_FACADE 1, REQUIRED_ADJ 3 | NO_FACADE 3, REQUIRED_ADJ 1 | — (Président 16,8 × 9,6 m: the original defect) |

Exploration over seeds 1, 3, 5, 7, 9, 11 (anneal seeds 1 and 6, 1 500–3 000 iterations):
`NO_FACADE` ends at 2–3 in every run. Before the seeding penalty, seeds 7 and 11 also ended with
2–3 `FACADE_DEPTH` (a shallow 8-module block of small offices against a 16-module block); with
it they still do (the plan basin is fixed by the room-bay/stack split), but the conventional
seeds (1, 3, 5, 9) give `FACADE_DEPTH = 0`.

**Why `NO_FACADE ≤ 1` is out of reach here.** With `dmax = 12` the 26-module bar has one band
and `D_A = D_B = 12` (any other split puts a façade room bay deeper than 12). At depth 12:
- the eight 16 m² rooms (6 chefs de service, 2 secrétariats; 45–48 cells) cannot be room
  bays (width 4 → aspect 3) and pair only with each other in a stack (8 × 6 + 8 × 6). No
  service room can be the inner partner of a 16 m² room (I checked every width: the 20 m² and
  4 m² sanitary rooms never fit with `h₁ + h₂ = 12` inside both area rules). So four two-room
  stacks, and each inner room has a façade only against an end wall;
- the west end wall (u = 0) of each block gives two inner rooms a façade, so the floor is
  **2** unless one block is filled **exactly** (`Σ widths = 90`, no end strip) with a finger
  bay at its east end too. Such packings exist (e.g. `[stack|finger] P08 P01 P09 P04 P06 P07
  [finger|stack]` = 10 + 7 + 38 + 6 + 7 + 6 + 6 + 10 = 90, with the services and the
  remaining 4 small rooms in the other block → `NO_FACADE = 1`, `REQUIRED_ADJ = 1`), but they
  need several coordinated moves (split a two-stack finger bay, move services, hit an exact
  width sum) that no single move or polish step of the optimiser makes, and the cost function
  gives no gradient towards an exact fill.

I prototyped an "end-wall" polish neighbourhood (move the finger bay of a lacking stack room to
the block end, mirrored, with room bays that fill the end strip exactly). On the D05 runs it
produced no candidate (the far-end bay was a services bay, so every move split a zone), and I
did not keep it. Reaching ≤ 1 needs either a frontage-packing search (subset sums over bay
widths with zone runs) or the grammar change that lets the end strip sit before the last
finger bay; both are beyond this ticket.

## 4. Gates
- ruff check: clean. ruff format --check: clean. mypy strict on `src`: 0 errors.
  `lock --check`: OK. `export_schemas --check`: OK.
- Whole suite under coverage (`pytest --cov=src/ale --cov-branch`), twice:
  - run 1: RUN1
  - run 2: RUN2
- Coverage of the touched packages: COVERAGE

## 5. Spec issues
1. **Soft aspect needs its own code.** `n_hard` is a count of codes in `HARD_CODES`, so "the
   `ASPECT` violation becomes soft" is implemented as a distinct soft code `ASPECT_DEPTH`
   (still reported, listed in the report section). Consumers that count `ASPECT` as hard stay
   correct.
2. **`2 · Dmax²`** is the `amax = 2` case of `amax · Dmax²`; the implementation uses
   `shape.aspect_max`.
3. **"With façade contact".** The rule applies to rooms whose exterior contact is at least `f`
   (rooms below `f` already carry `NO_FACADE`), so one room gets at most one façade violation.
4. **D05 programme.** The brief's line list (12 groups) gives 16 lines only when each
   vice-président, chargé de mission and H/F+PMR sanitary block is its own line and each
   secretariat is a line of its own (needed anyway for "each secretariat → its director");
   that is what the test does (25 rooms, 649 m²). eval.md says "others 4–31 m²"; the brief's
   list (4–30 m²) is used. The test rulebook has no `waiting_area` / `cleaning_room` types, so
   the salon is a `reception` and the local ménage a `storage` room.
5. **D05 target not reachable** with the current grammar and optimiser (§3).
6. **Config tests outside the ownership.** Adding a key to `AleConfig` breaks three key-count
   tests in `tests/cli` (`test_config.py::test_C01_defaults_complete`, `test_C04_frozen`,
   `test_init.py::test_I03_template_config_valid`). They were updated minimally: the expected
   defaults gain `facade.max_depth_m: None`, the frozen-field count goes to 45 + 16, and the
   template key count skips keys whose default is `None` (a TOML file cannot hold `None`, so the
   template `src/ale/templates/ale.toml`, not owned, is unchanged; a commented example line
   there would help users and is left to its owner).
7. **D02 baseline.** "Byte-identical to before" is checked against SHA-256 digests of the
   pre-Q.4 layouts, recorded in the test from a run of `12b59b0`.
