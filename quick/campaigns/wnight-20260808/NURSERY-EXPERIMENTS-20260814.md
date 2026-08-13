# Nursery-size experiments — 2/4/8/16 MB, all dimensions (2026-08-14)

Battery `nsweep` on church, fork `1d265d3a6` (post-round-31), fixed 192 MB
heap for D1/RSS (vanilla reference = wcomp8's medians, identical config),
dynamic heap for D4 streams. 2 reps for D1 (spread on this host ≤1% except
matmul's known ±5% lottery); pause streams for bt/kb/mature_mutation.

## The numbers

**D1 — cycles vs vanilla** (lower = closer):

| bench | n2 | n4 | n8 | n16 (default) |
|---|--:|--:|--:|--:|
| binarytrees | 1.60 | 1.49 | 1.37 | **1.25** |
| weak_memo | 1.89 | 1.27 | 1.11 | **1.02** |
| kb | 1.27 | 1.23 | 1.13 | **1.10** |
| spectralnorm | 1.15 | 1.07 | 1.08 | **1.05** |
| LU | 1.31 | 1.13 | **1.10** | 1.15 |
| mature_mutation | **1.95** | 2.20 | 2.83 | 2.41 |
| fragmed | 3.45 | 3.32 | 3.33 | 3.41 (flat — band-bound) |
| nbody/fannkuch/mandel/matmul | 1.00 | 1.00 | 1.00 | 1.00 |
| **geomean (11)** | 1.396 | 1.316 | 1.309 | **1.271** |

**D3 — pause profile (mean / p95 / max ms):**

| bench | n2 | n4 | n8 | n16 |
|---|---|---|---|---|
| binarytrees | 1.7 / 7.2 / **15.7** | 3.6 / 14 / 35 | 6.5 / 25 / 115 | 11 / 56 / 136 |
| kb | 0.4 / 0.6 / **2.3** | 0.9 / 2.6 / 3.0 | 1.5 / 1.8 / 3.0 | 2.7 / 3.6 / 6.7 |
| mature_mutation | 3.8 / 5.5 / **20** | 8.3 / 10 / 25 | 24 / 43 / 45 | 35 / 42 / 43 |

(vanilla: bt max 14.9, kb max 0.8, matmut max 2.0 — bt@n2 is at parity.)

**D4 — dynamic-heap RSS peak (MiB), vanilla in parens:**

| bench | n2 | n4 | n8 | n16 |
|---|--:|--:|--:|--:|
| kb (10) | **20** | 26 | 26 | 30 |
| spectralnorm (5) | **15** | 17 | 21 | 29 |
| binarytrees (141) | 174 | 172 | **145** | 159 |
| mature_mutation (26) | 68 | 69 | **61** | 64 |

## What each size argues

**n2 (stock parity).** *For:* vanilla's own minor-heap size; pause parity
(bt max 15.7 vs vanilla 14.9); best small-program RSS (kb 20, sp 15 —
right at the stated ~10 MB fixed-cost + nursery accounting); best
mature_mutation D1 (1.95 — fewer survivors per pause AND its cycles avoid
compaction stalls). *Against:* worst throughput almost everywhere else —
bt 1.60, weak_memo 1.89, LU 1.31, kb 1.27; geomean 1.40. The per-minor
fixed cost (~10× more minors than n16) is unaffordable until the
per-promotion cost (#27) comes down. Also: mature_mutation's compaction
law does not run in the cycle regime, so its *fixed-heap* RSS regresses
to ~170 MB at n2/n4 (the dynamic-heap curve stays fine at 68).

**n4.** *For:* biggest single jump in the whole sweep — weak_memo
1.89→1.27, LU 1.31→1.13, bt 1.60→1.49; still latency-mode (sliced
cycles, bt max 35 ms); small-program RSS nearly n2's (kb 26, sp 17).
*Against:* still 4.5 points of geomean behind n16; mature_mutation
begins its climb (2.20).

**n8.** *For:* best LU (1.10), best bt RSS (145 dyn / 140 fixed), within
0.04 geomean of n16; a genuine middle. *Against:* it is the *worst*
mature_mutation (2.83 — its 8 MB pressure floor lets the compaction law
fire most often while pauses are already large); bt max pause 115 ms —
nearly n16's latency with only part of n16's throughput.

**n16 (current default).** *For:* best D1 geomean (1.271), best bt
(1.25), weak_memo at parity (1.02), kb 1.10. *Against:* worst pauses
across the board (bt 136 ms max, matmut 43); worst small-program RSS
(kb 30, sp 29 — the +16 MB nursery term in the D4 accounting).

## The pattern, and what it says about a rule

Per-bench winners line up with **live-set size**: small-live programs
(kb, sp, weak_memo at n4+; LU) peak at 4–8 MB; the big-live program (bt)
keeps gaining through 16; the adversarial promoter (mature_mutation)
wants small. That is exactly the shape a heap-coupled rule —
`nursery = clamp(heap/8, 2 MB, 16 MB)` — would pick per bench: kb/sp/
weak_memo → ~4 MB (their dynamic heaps sit at the 32 MB floor), LU → 4–5,
bt → 16 (capped), mature_mutation → ~8. Reading those cells out of the
tables above, the coupled rule's projected geomean is ≈ 1.29 — within a
point or two of flat-n16 on D1 — while taking n4-class pauses and
n4-class RSS on every small program. It loses only bt's last two D1
points if bt's heap estimate lags its ramp.

## Recommendation

1. **Keep n16 as the flat default today** (D1 is the headline dimension
   and n16 wins it outright), with `@2M` documented as the latency
   configuration — unchanged from the current story.
2. **Implement the heap-coupled nursery as the next default candidate**:
   the sweep says it buys n4's D3/D4 on small programs at ~1 geomean
   point of D1. It needs one mechanism (re-bound the nursery when the
   dynamic heap retargets after a full) and one battery to validate.
3. Re-run this sweep after the per-promotion cost work (#27): every
   argument against small nurseries is "minors are too expensive per
   object" — if that falls from ~350 to ~150 cycles, n4 (or coupled)
   plausibly becomes the D1 winner too, and the whole trade collapses
   toward vanilla's configuration.
