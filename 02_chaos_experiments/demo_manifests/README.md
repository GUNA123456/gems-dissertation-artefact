# Demo-paced chaos manifests

The four manifests the supervisor-demo run sheets apply (`kubectl apply -f
~/gems/demo-<scenario>.yaml` on the VM). Identical stage magnitudes to the
collection ramps in `../chaos_manifests/v2_ramped/`, but **3-minute stages
(13 minutes total) instead of 5-minute (21 minutes)** — a live audience does
not need the extra eight minutes, and every "T+" cue in the run sheets is
timed against this pacing.

| File | Scenario | Stages |
|---|---|---|
| `demo-redis.yaml` | redis network delay | 150 / 400 / 900 / 1600 ms |
| `demo-cart-mem.yaml` | cart memory ramp to OOM | (see file) |
| `demo-payment.yaml` | payment network delay | (see file) |
| `demo-catalog-cpu.yaml` | catalog CPU stress | (see file) |

Do not swap these with the collection versions: applying a 21-minute ramp in a
demo desynchronises the run-sheet narration, and applying a 13-minute ramp in a
collection night changes the precursor window the datasets were built on.

Verified byte-identical to the VM copies (md5) when rescued into version
control on 2026-08-23.
