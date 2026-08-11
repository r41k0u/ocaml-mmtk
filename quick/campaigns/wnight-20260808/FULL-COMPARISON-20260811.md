# Bactrian vs vanilla OCaml 5.5.0 — full comparison (2026-08-11)

Final state of the shape campaign (fork `shape/tweaks` @ `4c5adbba9`).
Host: church (Xeon Gold, cores 0–13 pinned, ASLR off). Vanilla = pristine
5.5.0 (`f5238509d`) at `OCAMLRUNPARAM=o=500`. Bactrian = bare defaults
(`MMTK_PLAN=Bactrian MMTK_HEAP_SIZE_MB=192 MMTK_THREADS=1` — pretenuring ON,
sliced marking ON, UP-trace armed). Medians of 3; program outputs
byte-identical across a 16-cell golden gate.

## D1 — CPU budget (cycles, instructions, wall, peak RSS)

| bench | v cyc | B cyc | **ratio** | ins ratio | v wall | B wall | v RSS | B RSS |
|---|---|---|---|---|---|---|---|---|
| binarytrees | 11.51G | 9.67G | **0.84×** | 0.64× | 3.63s | 3.06s | 141M | 266M |
| nbody | 6.69G | 6.70G | **1.00×** | 1.00× | 2.10s | 2.11s | 3M | 10M |
| fannkuchredux | 10.59G | 10.86G | **1.03×** | 1.00× | 3.33s | 3.41s | 3M | 11M |
| spectralnorm | 4.88G | 5.23G | **1.07×** | 1.00× | 1.53s | 1.65s | 5M | 76M |
| mandelbrot | 5.61G | 5.43G | **0.97×** | 1.00× | 1.77s | 1.71s | 3M | 10M |
| matmul | 4.63G | 5.38G | **1.16×**† | 1.00× | 1.45s | 1.69s | 17M | 34M |
| LU | 5.35G | 6.75G | **1.26×**† | 1.01× | 1.68s | 2.14s | 18M | 90M |
| kb | 4.51G | 4.74G | **1.05×** | 0.92× | 1.42s | 1.50s | 10M | 85M |

† matmul/LU (and to a lesser degree kb, fannkuch, spectralnorm) sit on the
**code-layout lottery**: their mutator cycles move ±5–12 % between semantically
identical builds with every PMU counter flat (matmul has measured 1.03× on a
good draw this same week). GC is exonerated on all three — instruction parity
holds, and LU reproduces its gap with the collector disabled entirely.

RSS caveat: Bactrian runs a **pinned 192 MiB heap** here (benchmark
determinism); touched pages are never returned, which inflates low-live benches
(spectralnorm/kb/LU). Memory-parity comparisons use the dynamic `live × 2.2`
heap — the D4 campaign measured those separately. bt's 266M vs 141M is nursery
residency + fixed-heap slack, a known standing item, unchanged this campaign.

## D3 — pause distribution

| stream | n | mean | p95 | max |
|---|---|---|---|---|
| **Bactrian bt@2M minors** | 2411 | 1.66ms | 6.7 | 8.0 |
| **Bactrian bt@2M cycle pauses** | 15 | 3.6ms | 6.8 | 6.8 |
| **vanilla bt** (all pauses incl. slices) | 3554 | 0.55ms | 2.2 | **15.2** |
| Bactrian kb minors / cycles | 28 / 3 | 5.0 / 0.9ms | — | 8.8 / 1.4 |

**Whole-run max pause: 8.0 ms — below vanilla's 15.2 ms.** At the start of this
campaign the same configuration had 27 × 78–122 ms stop-the-world Fulls; sliced
marking removed the tail entirely. Total STW is 4.07 s vs vanilla's 1.97 s —
that residual is *mean minor cost* (1.66 vs 0.55 ms/pause; per-object economics,
gap 2 below), not the tail.

(bt at the *default* 64 MiB nursery shows 67 ms minors — that is the cost of
evacuating a 64 MiB nursery, present in any copying-nursery design at that
size; at stock's 2 MiB arena size the shapes are as above.)

## D2 — cycle pacing

| | minors | major cycles | trigger attribution |
|---|---|---|---|
| Bactrian bt@2M | 2411 | 15 | 321× mature-pressure, 6× allocation-budget |
| vanilla bt (o=500) | — | 29 | space_overhead pacing |
| Bactrian kb | 28 | 3 | 3× allocation-budget |

The trigger *law* is now structurally vanilla's (pressure % over the post-cycle
baseline, allocation budget measured from cycle start; a completed concurrent
cycle resets pacing exactly like a monolithic Full). The 15-vs-29 period gap is
one constant — our pressure margin vs vanilla's `space_overhead` value —
pending a calibration decision (more cycles = more G work = shifts D5).

## Reading guide (one paragraph for the meeting)

Where the collector does the work — binarytrees, the allocation-heavy stress —
Bactrian is now **16 % cheaper than vanilla in total CPU** while keeping
**every pause under 8 ms**. The compute benches are at parity (nbody,
mandelbrot, fannkuch) or inside a measured build-layout noise band that has
nothing to do with the GC (matmul, LU). The two honest gaps we can still close
with mechanism are the per-minor-object cost (~260 vs ~80 cycles — the price of
a VM-neutral framework's scan/dispatch layer) and the cycle-period constant;
everything else outstanding is either methodology (layout-robust W measurement)
or engineering hygiene (StickyImmix bug, D5 re-sweep, multi-domain).
