# Ticket 0.3 — Seed Rulebook · Requirements Document

**Owner: the architect (user).** No Worker is dispatched for this ticket. The Router drafted
the template; the user supplies the values.

## Purpose

Give the generator (Phase 3) the architectural knowledge it needs before any plan has been
mined: per room type, the accepted proportions, typical areas and façade preferences; which
types should and should not touch; and where the service core usually sits.

## Deliverable

`seed_rulebook.yaml`: a filled copy of `seed_rulebook.template.yaml` (same folder), committed at
`specs/tickets/0.3_seed-rulebook/seed_rulebook.yaml`. Later copied into workspaces with
`ale rulebook build --seed-rulebook`.

## What the user supplies (all in the template, every `null`)

| Block | Per | Values | Rule |
|---|---|---|---|
| `author`, `date` | file | 2 | non-empty; `YYYY-MM-DD` |
| `types.<t>.aspect` | room type | p10, p50, p90 — **pre-filled 1.0 / 1.4 / 2.0** (user rule U-2), review only | 1.0 ≤ p10 ≤ p50 ≤ p90 ≤ 6.0 (long/short side) |
| `types.<t>.area_m2` | room type | p10, p50, p90 | 0 < p10 ≤ p50 ≤ p90 (m², one room) |
| `types.<t>.orientation` | room type | N, E, S, W | each in [−1, 1] |
| `adjacency.default_p` | file | 1 | [0, 1] |
| `adjacency.pairs[].p` | listed pair | 30 (more may be added) | [0, 1] |
| `core_offset` | file | dx_norm, dy_norm | each in [−0.5, 0.5] |

Room types that are not needed yet may be deleted from `types:`. A program that uses a deleted
type is refused at generation time with a message naming the type.

## Constraints

- Types listed must exist in `taxonomy.yaml` v1 (Ticket 0.2); `circulation` and `unknown` are not allowed.
- The types used by the shared test fixtures of Ticket 0.4 must not be deleted:
  `office, open_office, meeting_room, entrance_hall, reception, sanitary, sanitary_accessible,
  storage, technical_room, it_room, kitchenette, stair, lift`.
- The aspect band is a preference (soft cost), per the user's "approximately 1:1 to 1:2". Bands narrower
  than 1.0–2.0 are allowed; on the 0.10 m grid they rarely conflict with the area rule, and when they do the
  area rule wins and the aspect deviation is costed (decision O-2).
