# A.1 — Router notes

Contract amendment required by user decision U-6 (corridor grammar). Design: `specs/design/corridor_grammar.md`.
Verified expectations: site_L → vertical cut, J2, primary (0,0,300,300) X, secondary (300,0,180,180) X;
J1 example → vertical cut, primary (0,0,200,300) Y, secondary (200,0,400,120) X, facing block B.

## Review log
- 2026-11-07 — Attempt 1 (commit a2ba097): 33 tests, 100 % coverage, existing contracts untouched; edited `test_serialization.py` version literal (necessary, accepted). Worker found that Router eval F04 was wrong: with the tie rule "square primary → X", site_L rotated 90°/270° gives J1, not J2. Rule amended rather than the test: square primary takes the spine axis perpendicular to the cut (rotation-invariant). Rework requested.
- 2026-11-07 — Attempt 2 (fe73be6): tie rule fixed; Router independent check: 8 orientations → J2, pieces 90 000 / 32 400; J1 example unchanged. Merged on top of 3.1: 501 pass, lock + schemas OK. **DONE**, contracts 1.1.0.
