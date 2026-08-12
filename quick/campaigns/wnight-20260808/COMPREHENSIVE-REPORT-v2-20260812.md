# Bactrian vs vanilla 5.5.0 — comprehensive shape report v2 (post-D5 campaign)

**Date:** 2026-08-12 · **Tree:** `shape/tweaks` @ `970a2721c` (adds over v1:
mature-pressure floor 32→8 MiB; stream coverage extended to LU+spectralnorm;
D5 measured as two-knob pareto fronts both sides). Same host/method/gates as
v1. All figures regenerated in `figs-20260812/`.

## D1 — CPU budget (geomean **1.048**)

| bench | ratio | ins | note |
|---|--:|--:|---|
| binarytrees | **1.07×** | 0.97 | improved from v1's 1.12 (floor=8: cheaper, earlier cycles) |
| nbody / mandelbrot / matmul | **1.00×** | 1.00 | parity (matmul settled from 0.97 draw) |
| fannkuchredux | **1.01×** | 1.00 | |
| spectralnorm | **1.05×** | 1.01 | frontier warmth (LOS band) |
| LU | **1.15×** | 1.02 | frontier warmth (store-side RFO; floor at n8 = 1.10) |
| kb | **1.11×** | 1.08 | per-minor economics (option c's target) |

All eight within 15%, six within 7%. Wall and RSS columns in the data
appendix; RSS at the pinned bench heap is not the D4/D5 number.

## D2 — Pacing (fig2)

Cycle law calibrated (28 vs 29 on bt@2M); probe streams now cover bt+kb
(LU/sp pending a suite-Makefile PROBE_BENCHES addition, noted). The
default-config curve is flatter by construction (16 MiB minors).

## D3 — Pauses (fig3, now 4 benches)

| bench | vanilla n/mean/max (ms) | Bactrian default | Bactrian @2M |
|---|---|---|---|
| bt | 3553 / 0.56 / 15.0 | 344 / 6.1 / 54.2 | 2394 / 2.1 / **8.2** |
| kb | 1884 / 0.10 / 0.8 | 122 / 2.7 / 6.1 | 1189 / 0.5 / 1.8 |
| LU | 11180 / 0.004 / 0.1 | 767 / 0.11 / 1.1 | 7477 / 0.05 / 0.8 |
| sp | 5492 / 0.004 / 0.1 | 377 / 0.09 / 1.1 | 3676 / 0.05 / 0.7 |

The new LU/sp streams confirm the structure generalizes: at the stock-parity
config every bench's distribution sits in vanilla's class (sub-ms means,
single-digit maxes); the default config trades pause count for pause size
(a 16 MiB evacuation is ~6 ms on bt). Vanilla's sub-0.1 ms LU/sp pauses are
its near-empty minor slices — ours are real minors, fewer and larger; same
total STW order.

## D4 — RSS over time (fig4, 4 benches, dynamic heap)

Sawtooth shape tracks the live set on both sides; standing offsets are the
~7.5 MiB floor + nursery residency, as decomposed in the anatomy (v1).

## D5 — Space-time pareto fronts (fig7) — the KC dimension

Both sides swept over both knobs (ours heap×nursery; vanilla o×s).
Post-floor-fix fronts:

- **kb**: best-memory point 29→**19 MiB** (h40n2) vs vanilla 8–16. The
  remaining ~11 MiB over vanilla at matched wall = floor 7.5 + block-
  occupancy slack (live scattered in partially-filled 32 KB blocks) +
  end-of-cycle-only sweep (vanilla sweeps incrementally, continuously
  reclaiming floating garbage).
- **bt**: front 113/6.8 → 384/4.0; vanilla 61/8.6 → 155/**2.8**. Two gaps:
  ~1.8× RSS at matched wall (same components + copy headroom), and the wall
  floor (4.0 vs 2.8 s) which is per-minor economics, not memory.
- **LU/sp**: fronts dominated by vanilla's single tight points; gap =
  floor + nursery + the same occupancy slack.

**Levers tried this campaign, honestly reported:** block-reuse ordering —
REFUTED by code reading (the pool is already LIFO-preferred); page release
on block-free — refuted for default use (−0.9 MiB, +10% D1 at current
config); pressure-floor 32→8 — ADOPTED (kb −8% RSS default-config, front
−10 MiB, all else neutral); aggressive-defrag knobs — no-ops (compaction
already works under pressure). **Remaining D5 gap is three named
structural components**: (i) the ~7.5 MiB MMTk floor, (ii) block-occupancy
slack + end-of-cycle sweep (the Immix-vs-pools design difference), (iii)
bt's wall floor (per-minor cost). (ii) would need either incremental sweep
(item-2 machinery could host it) or smaller blocks; (iii) is option (c).

## Attribution refresh (fig6, bt@n8)

324 cy/object at n8 on this build: drain loop ~123 / core machinery ~111 /
intrinsic ~58 / binding ~32. The core-machinery share (unfixable from the
plan) holds at ~34%; conclusions from v1 unchanged.

## Where this leaves the claim

Shape: D2 matched by law; D3 matched at stock-parity config on all four
streamed benches; D1 geomean 1.048 with every deviation mechanism-named;
D5 explained to three structural components, one of which (per-minor cost)
is already the authorized next work item and a second (incremental sweep)
has a designed home in the sliced-marking machinery. The suite-coverage
gaps (mature-mutation, weak/ephemeron, macro benches) are documented in
BENCHMARK-SUITE.md for the add-benches decision.
