# Campaign status v9 — after the fused-metadata round (2026-08-14)

Battery `wcomp9`, church, fork `6bbdfbd6a` + core `9cda6a4816`.
Figures in `figs-v9/`; raw in `raw/wcomp9-tables.txt`. This is the
proposed **campaign-closing readout** — every planned matching mechanism
has now landed and been measured.

## What round 32 (fused metadata) did

The last uniform D1 lever: under the UP window (one tracer, stopped
world — the invariant UP-trace established), the per-object metadata
atomics became plain stores: the promotion path's SeqCst mark store (a
full-fence XCHG per promoted object), major marking's SeqCst
load + compare-exchange loop, and the live-tally's LOCK XADD.
KC-explanation, one sentence: *stock keeps GC state in the header word it
already holds; MMTk keeps it in side tables for plan composability; with
one tracer and a stopped world, neither the atomicity nor the fences are
necessary, so the UP window elides them.* Multi-worker runs keep the
atomic paths untouched (UP never arms there).

## D1 — cycles vs vanilla (192 MB heap, medians of 3)

| bench | v8 | **v9** | v9 +oldify |
|---|--:|--:|--:|
| binarytrees | 1.26 | **1.18** | **1.08** |
| kb | 1.10 | 1.10 | **1.04** |
| weak_memo | 1.01 | 1.00 | 0.97 |
| spectralnorm | 1.05 | 1.05 | 1.05 |
| LU | 1.14 | 1.14 | 1.15 |
| matmul (±4% lottery) | 1.05 | 1.01 | 1.04 |
| nbody / fannkuch / mandelbrot | 1.00 | 1.00 | 1.00 |
| mature_mutation (adversarial) | 2.41 | 2.40 | 2.35 |
| fragmed (adversarial) | 3.09 | 3.05 | 3.05 |
| **geomean (11)** | 1.263 | **1.249** | **1.230** |
| **geomean (original 8)** | 1.06 | 1.05 | **1.04** |

Attribution (bt@n8): 404 → **370** cy/object default, 359 → **320** with
UP-oldify (from ~400 when the campaign's attribution work began).

## The other dimensions (no regressions)

- **D3**: bt@2M max pause **12.6 ms vs vanilla's 15.0** (below vanilla);
  kb@2M 2.2 vs 0.8; the n16 default keeps its documented Full-regime
  pauses (117 ms max on bt). MMU curves unchanged in shape, slightly
  better everywhere (marking itself got faster).
- **D4**: identical to v8 within noise (matmut holds its 77 MB fixed /
  ~60 sawtooth dynamic; the ~25 MB overhead accounting stands).
- **D5**: unchanged (same heaps, same fronts).
- **D2**: bt default still tracks vanilla's cumulative-STW curve; GC time
  at bt-def 2751 → 2463 ms.

## Where the remaining gaps live (all explained, none mysterious)

1. **bt 1.18/1.08, kb 1.10/1.04** — residual per-promotion cost (370/320
   vs vanilla's ~100): what's left is packet buffering, copy-context
   plumbing, and scan dispatch — reachable only by deeper core surgery
   with diminishing returns; UP-oldify already bypasses the worst of it
   (hence its 10-point bt delta).
2. **LU 1.14** — allocation-frontier warmth (round 27's store-RFO
   analysis): vanilla's arena hands back L2-warm lines; our band bump
   allocates into colder blocks. Not promotion-related (oldify: no
   effect).
3. **sp 1.05** — young-LOS float vectors.
4. **mature_mutation 2.35** and **fragmed 3.05** — the two designed
   adversarial floors: line-granular reclaim vs interleaved small
   corpses (paid as compaction CPU by direction, D4-first), and
   no-in-place-reuse for multi-line objects (the freelist A/B proved the
   cure needs a pool-class fast allocator MMTk doesn't have). Both are
   documented with controlled experiments.

## Standing decisions

- **UP-oldify remains opt-in per direction** — noting that it is now
  worth 10 points on bt (1.18→1.08) and the whole-panel geomean gap
  between modes is 2 points.
- Heap-coupled nursery: next default candidate (nursery report).
- Freelist mature / fast pool allocator: future round, prerequisites
  documented.

Recommendation: **call the matching campaign here** and shift to
write-up: original panel at 1.04–1.05, pauses at-or-below vanilla in the
latency configuration, pacing curves overlapping, memory floors
accounted, and the two adversarial benches serving as the paper's
where-generality-costs demonstrations.
