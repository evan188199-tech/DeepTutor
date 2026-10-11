# Measured results — Mastery Path replayed-history duplication

- repo head: `6cf793bd868b`
- token estimator: `tiktoken/cl100k_base` (serialized-JSON planning estimate, not provider billing)
- fixture: shape-faithful mastery tool payloads replayed through real `replay_history`; offline, no LLM

## Assembly × duplication × size matrix

| scenario | turns | msgs | bytes | tok~ | tool-result % | whole-msg dup % | subtree dup % |
|---|---:|---:|---:|---:|---:|---:|---:|
| dialogue-only baseline (20 turns, no mastery tools) | 20 | 40 | 12,432 | 3,081 | 0.0 | 77.3 | 0.0 |
| mastery S (3x5, 5 turns) | 5 | 47 | 116,980 | 34,938 | 94.3 | 1.7 | 50.3 |
| mastery S (3x5, 10 turns) | 10 | 98 | 235,627 | 70,507 | 94.2 | 1.9 | 48.0 |
| mastery S (3x5, 20 turns) | 20 | 194 | 464,344 | 139,250 | 94.2 | 2.1 | 49.3 |
| mastery M (6x8, 5 turns) | 5 | 47 | 297,760 | 90,546 | 97.8 | 0.7 | 54.4 |
| mastery M (6x8, 10 turns) | 10 | 98 | 597,187 | 181,723 | 97.7 | 0.8 | 51.6 |
| mastery M (6x8, 20 turns) | 20 | 194 | 1,174,728 | 357,983 | 97.7 | 0.8 | 53.0 |
| mastery L (10x12, 5 turns) | 5 | 47 | 687,130 | 210,306 | 99.0 | 0.3 | 55.9 |
| mastery L (10x12, 10 turns) | 10 | 98 | 1,375,925 | 421,243 | 99.0 | 0.3 | 53.0 |
| mastery L (10x12, 20 turns) | 20 | 194 | 2,704,829 | 829,083 | 99.0 | 0.4 | 54.4 |

Legend: *tool-result %* = share of replayed-history bytes in `role=tool` messages. *Whole-msg dup %* = bytes in byte-identical repeated messages. *Subtree dup %* = bytes in JSON subtrees (top-level payload keys) that appear identically in an earlier tool result of the same history.

## Per-turn carriage (one new turn, 3 main-loop rounds)

| prior turns | per-round tok~ | total tok~ | history carried per round tok~ | ratio |
|---|---|---|---|---|
| turns=10 | 184049, 190872, 197696 | 572,617 | 181,723 | 3.11x |
| turns=20 | 360309, 367132, 373956 | 1,101,397 | 357,983 | 3.06x |

## Runtime snapshot accumulation

| turns | snapshot rows retained | bytes | share of history |
|---|---:|---:|---:|
| turns=5 | 5 | 1,030 | 0.35% |
| turns=10 | 10 | 2,061 | 0.35% |
| turns=20 | 20 | 4,131 | 0.35% |

## One mastery_status payload, key anatomy (6 modules × 8 KPs)

- total payload: 20,733 B

| key | bytes |
|---|---:|
| map | 16,238 |
| visual_requirements | 2,161 |
| learning_stages | 1,057 |
| learner_profile | 370 |
| next | 322 |
| sources | 241 |
| pending_interaction | 212 |
| goal | 58 |
| path_name | 35 |
| path_id | 18 |
| status | 8 |
| mode | 7 |
| intake_needed | 5 |
| path_revision | 1 |

- whole keys byte-stable across two consecutive calls (differ by one graded KP): 13.8%
- per-KP entries inside `map` byte-identical between the same two calls: **89.7%** (14,566 of 16,238 B)

