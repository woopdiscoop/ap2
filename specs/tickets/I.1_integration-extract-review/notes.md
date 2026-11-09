
## 2026-11-09 — Router ruling on conflicting legacy tests
Codex reported 3 pre-I.1 tests that assert behaviour I.1 replaces: DB `user_version == 1`, PDF/raster extraction
"not implemented", and `north_angle_deg` rejected / ignored as an unknown meta column. I.1's RD supersedes them. The
Worker is authorised to update **exactly those assertions** to the I.1 behaviour (user_version 2 after migration,
PDF/raster extraction works, `north_angle_deg` accepted), with no other weakening, and to list each changed test
(file::name, old → new assertion) in `eval_report.md`. The Router re-checks each one at review.
