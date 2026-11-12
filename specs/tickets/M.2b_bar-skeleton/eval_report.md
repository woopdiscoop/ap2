# Ticket M.2b · Evaluation report (WIP)

## Diagnosis (B201)

Reproduced with synthetic bars (see Results for the harness). `decompose_footprint` treats a solid as a hole, so a
bar with an interior solid becomes a ring of 4 rectangles (pinwheel) chosen by the key
`(pieces, J2 count, largest aspect, tuples)`. The key prefers all-J1 junctions, which always gives a pinwheel.

Bar 54.0 x 15.6 m, solid 6.0 x 6.0 m at (24.0 ; 4.8), load 0.97 (`fill_ratio`):

| piece | rect (x, y, w, h) m | spine | note |
|---|---|---|---|
| 0 | (0, 0, 54.0, 4.8) | X | root, 4.8 m deep: one-sided |
| 1 | (0, 4.8, 24.0, 10.8) | Y | wide piece whose spine runs along its short side |
| 2 | (24.0, 10.8, 30.0, 4.8) | X | J1 child of piece 1 |
| 3 | (30.0, 4.8, 24.0, 6.0) | Y | J1 child of piece 0, 6 m long spine in a 24 m wide piece |

Junctions: J1 (0,1), J1 (0,3), J1 (1,2); open contact (2,3). Every seed fails (0/10): the realiser reports
`BLOCK_TOO_SHALLOW` (piece 0 given 2 bands in a 4.8 m deep strip, a block of depth 0 holding rooms),
`JUNCTION_MISALIGNED` ("no junction finger to 1/3": the finger that links a child is missing, or lies outside the cut),
`PLAN_OVERFLOW`, `ROOM_INFEASIBLE`. Over 67 realisations of one run: 34 plans with all pieces single band fail on
{too shallow, misaligned, overflow, room infeasible}, 12 with piece 0 on 2 bands fail on {too shallow, misaligned}.

Why the junction check rejects them: a J1 child must hang on a finger that lies inside the cut segment and puts the
child's spine inside the child. For the pinwheel pieces, the parent's facing block is too short or too shallow to hold
the rooms that must precede the finger; the finger is then placed at the start of the block (target before the first
bay boundary inside the window), the child's spine falls outside its piece, `JUNCTION_MISALIGNED`.

The H decomposition (two full-depth wings + two strips, all J2) is rejected by the key and cannot work either: J2 needs a
single shared absolute spine band, but the top and bottom strips need bands 10.8+ and 0-3 m while the wing has one band.
Contract rules (`CorridorPlan._check_tree`: J2-incident pieces have exactly one band) forbid a connector on a wing.

M.1 bar (64.8 x 19.2 m, solid 16.8 x 7.2 m at (30.0 ; 3.6)): works at low load (4/4 at 0.79) because one gap is
3.6 m (a leaf strip) and the other 8.4 m (a double-loaded root); a centred solid (gaps 6.0 m) fails whatever the
decomposition (16 variants tried at load 0.79).
