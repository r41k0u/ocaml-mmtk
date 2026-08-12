# v3 addendum — incremental sweep landed; D1 regression resolved to the wobble band

**Tree:** `shape/tweaks` @ `9785c43a8` (v2 + LOS-corruption fix + incremental
sweep + pause-gate hoist + floor=8). Figures in `figs-v3/`.

## What changed since v2

1. **Incremental sweep** (the user-chosen D5 avenue): FinalMark's mature
   sweep now runs as 2 ms quanta across subsequent minors — completing the
   sliced-cycle architecture (mark quanta + sweep quanta = stock's fully
   incremental major cycle). Freed memory returns across minors, not at one
   cliff.
2. **The sliced-marking × LOS corruption** found by the new probe gates —
   fixed same-day (see ISSUES-FIXED update / NOTES 2026-08-12).
3. **D1 regression chased**: the young-check hoist recovered ~40%; the v3
   battery medians put the rest inside the documented ±3% data-layout wobble
   (bt 1.07→1.10 while its *GC time improved* 2422→2196 ms — the delta is
   mutator-side noise, not collector cost). opt-level=z floor trim refuted
   (−0.1 MiB / +37% GC); margin recalibration refuted (14% → 28 cycles ≈
   target on the post-sweep baseline).

## v3 numbers

**D1** (geomean **1.046**): bt 1.10 · nbody/fannkuch/mandelbrot/matmul 1.00
· sp 1.05 · kb 1.09 · LU 1.14.

**D3 (bt@2M)**: whole-run max **8.0 ms** (vanilla 15.2); cycle pauses mean
**2.03 ms**, max 6.16 — the FinalMark sweep no longer bulges the pause.

**D5 pareto (fig7), incremental-sweep effect visible on the fronts:**
- bt mid-front wall improved ~13% at constant RSS (h96n16: 5.20→**4.53 s**
  at 127 M) — dead blocks recycle sooner, so the same heap does more work.
- kb front shifted left: new 25 M/1.69 s point (was 29 M); floor 19 M vs
  vanilla's 8–16 M.
- LU/sp fronts unchanged in shape (their gap is frontier warmth + floor).

**Attribution refresh (bt@n8)**: ~330 cy/object — drain loop 129 / core
machinery 105 / intrinsic 58 / binding 37. Core-unreachable share steady at
~32%.

## The open D5 design decision — automatic compaction

The largest remaining *mechanistic* D5 item: Bactrian's mature space never
defragments during normal operation (defrag runs only at STW Fulls, which
the pacing never schedules — cycles do it all). kb holds ~15 MiB of
partially-occupied blocks for ~2.5 MiB live. Stock OCaml's analog is
automatic compaction. Two candidate laws, both reusing the existing
(tested) Full+defrag machinery via a trigger only:

- **(A) utilization-threshold**: post-sweep, if live-lines / reserved-lines
  < X% (say 35), upgrade the next cycle to a compacting Full. Fires exactly
  when fragmented; needs a cheap utilization counter in the sweep.
- **(B) every-N-cycles**: simpler, blunter; periodic compaction cost on
  unfragmented workloads.

(A) is the vanilla-shaped law. Cost: one STW Full when it fires (~the
78–122 ms class we removed — rare, but it returns the D3 tail on firing).
Mitigation: compacting Fulls could themselves be capped/staged later.
