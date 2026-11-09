
## 2026-11-09 — Router ruling on conflicting legacy tests
Codex reported 3 pre-I.1 tests that assert behaviour I.1 replaces: DB `user_version == 1`, PDF/raster extraction
"not implemented", and `north_angle_deg` rejected / ignored as an unknown meta column. I.1's RD supersedes them. The
Worker is authorised to update **exactly those assertions** to the I.1 behaviour (user_version 2 after migration,
PDF/raster extraction works, `north_angle_deg` accepted), with no other weakening, and to list each changed test
(file::name, old → new assertion) in `eval_report.md`. The Router re-checks each one at review.

## 2026-11-09 — Router ruling: VLM stays out of I.1
I.1 keeps its RD scope: text-only labelling (`image=None, provider=None`). Point 3 of the previous message (call
`prepare_image`) is withdrawn because there is no image to prepare. Wiring the configured Claude provider into `ale extract`
(render the plan image, `prepare_image`, `make_provider(config)`, opt-in when `[vlm] provider` is set) becomes
follow-up ticket I.2 after I.1 merges.
