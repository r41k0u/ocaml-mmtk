# sedlex slowdown — diagnosis (2026-09-08)

Church, single GC worker (`MMTK_THREADS=1`), macro binary
`~/shape/macro/{mmtk,vanilla}/sedlex/sedlex_bench.exe` (Aug-30 fix-branch
build), node 0/1 pinned. Perf counters still locked (`paranoid=4`); all below
is wall + `MMTK_VERBOSE` + `Gc.stat`. The perf/flamegraph pass is CONFIRMATORY
now (the knob isolation already localises the cost), pending a counter unlock.

## What sedlex does

Generates a ~480 MB pseudo-code string, tokenizes it into ONE monotonically
growing list of tens of millions of boxed tokens (most holding a fresh
`lexeme` string), then `List.rev` + `List.length` + `List.iter`. The
generational hypothesis is fully violated: almost nothing dies young, the
live set only grows. Vanilla peak RSS 8.47 GB at the 6M-line default rung.

## The slowdown is a ~6x CONSTANT factor, not quadratic

| n (lines) | vanilla wall / RSS | Bactrian wall | ratio | Bactrian GC time | objects copied |
|-----------|-------------------:|--------------:|------:|-----------------:|---------------:|
| 500K      |               —    |      20.5 s   |   —   |      16.0 s      |   31.4M        |
| 1M        |  6.98 s / 1.40 GB  |      43.4 s   | 6.2x  |      34.4 s      |   63.5M        |
| 2M        | 13.94 s / 2.81 GB  |      81.3 s   | 5.8x  |      63.8 s      |  127.4M        |

Both runtimes linear in n; ratio stable ~6x. Objects copied scale
dead-linearly. This REFUTES the prior "object-grain remembered-set quadratic"
hypothesis (MACRO-PARITY-FINDINGS 2026-08-30): no super-linear term, and the
benchmark does no mutation, so the write-barrier remset is nearly empty.

## Where the gap is (pause-class split; n=1M, same 1.369 GB / 63.5M objects promoted)

Bactrian pause log (`MMTK_PAUSE_LOG`) vs vanilla runtime events (`olly trace`):

| component | vanilla | Bactrian | gap share |
|-----------|--------:|---------:|----------:|
| promotion (vanilla `minor_local_roots_promote` / Bactrian nursery pauses) | 2.08 s | 11.55 s (491 pauses) | +9.5 s (27%) |
| major work (vanilla 3685 `major_slice` / Bactrian 11 monolithic fulls)     | 0.56 s | 22.36 s | +21.8 s (61%) |
| mutator                                                                    | 4.31 s | ~8.8 s  | +4.5 s (13%) |
| **wall**                                                                   | 7.09 s | 42.7 s  | 35.6 s |

**Promotion cost per KB (the copy hypothesis): 5.56x.** Vanilla 1.55 us/KB
(~4.7k cycles/KB, ~98 cycles/object); Bactrian 8.64 us/KB (~25.9k cycles/KB,
~546 cycles/object). Same shape as the 415-vs-80 cycles/object UP-oldify
measurement (SHAPE.md 2026-08-10). Confirmed, but it is a QUARTER of the gap.

**The dominant term is the full collections (61%), and the trigger is now
proven.** `MMTK_PACE_DEBUG` at n=1M: 10 of the 11 fulls fire `by_cadence`
(binding `collection.rs`: `nb >= cadence_budget_bytes()` = 8 x 64 MiB = a
whole-heap re-mark every 512 MiB of NURSERY ALLOCATION since the last full,
`n=32` minors x 16 MB), only the 3 startup ones fire `by_mature` (baseline=0),
and `by_mature` never fires again. It is a fixed tax on allocation volume,
blind to survivors and headroom; vanilla paces incremental slices by allocated
words against `o=500` headroom and does 5 majors.

Dose-response (n=1M, pinned 8 GB):

| cadence law | fulls | full-pause sum | GC time | wall | vs vanilla |
|-------------|------:|---------------:|--------:|-----:|-----------:|
| `MMTK_FULL_GC_CADENCE=16` (full / 16 minors) | 31 | — | 101.0 s | 109.6 s | 15.5x |
| default (bytes backstop, 512 MiB)            | 11 | 22.36 s | 33.9 s | 42.7 s | 6.0x |
| `MMTK_FULL_GC_CADENCE=64`                    |  9 | — | 37.7 s | 46.5 s | 6.6x |
| **backstop off** (`MMTK_FULL_GC_CADENCE=100000`) | **4** | **6.85 s** | **18.3 s** | **26.8 s** | **3.8x** |

Margin-law sweep (`MMTK_MATURE_OVERHEAD_PCT` 100/150/200/500): flat at 11
fulls — confirms it is not the pacer. With the backstop off the 4 remaining
fulls are the 3 startup fires + one margin fire at 2.5x growth; promotion time
is unchanged (11.42 s), as it must be. **One knob removes 15.5 s = 44% of the
whole 35.6 s gap.**

**Mutator is 2x vanilla** (8.8 vs 4.3 s). Immix with 0 GCs runs the same
program in 6.1 s, so ~1.4x is the fork's allocation/barrier path and the rest
is GC cache pollution. A third, smaller lever.

Earlier draft of this note attributed ~100% to promotion from the heap-sweep
invariance; that inference was wrong — heap invariance meant the fulls were
cadence-driven, not that they were cheap.

## Mitigation landscape (measured; n=1M unless noted)

| lever | wall | RSS | vs vanilla time | note |
|-------|-----:|----:|:---------------:|------|
| vanilla o=500                | 6.98 s | 1.40 GB | 1.0x | reference |
| Bactrian default (16 MB nur) | 41-43 s| 1.47 GB | ~6x  | the problem |
| + UP-oldify                  | 37.3 s | 1.47 GB | 5.3x | free, stackable, -11% GC |
| nursery 64 MB                | 35.7 s | 1.42 GB | 5.1x | GCs 502->132 |
| nursery 256 MB               | 30.3 s | 1.69 GB | 4.3x | GCs 502->39, copies unchanged |
| Immix, default dynamic heap  | 12.75 s| 3.86 GB | 1.8x | copied=0, 6 marks |
| Immix, overhead=500 (~vanilla)| 8.10 s| 5.46 GB | 1.16x| copied=0, 3 marks |
| Immix, 8 GB pin              | 6.13 s | 7.71 GB | 0.9x | 0 GCs |
| StickyImmix                  | CRASH  |    —    |  —   | worker panic epilogue.rs:11 |
| MarkSweep                    | REJECT |    —    |  —   | free-list Default not native-supported |

At n=2M Immix/overhead500 holds at 18.2 s vs vanilla 13.9 s (1.31x): time
parity persists at scale.

**Stacked knobs (backstop off + nursery 256 MB + UP-oldify) — best available
today, no code change:**

| n  | Bactrian stacked | vanilla | ratio | RSS Bactrian / vanilla |
|----|-----------------:|--------:|------:|-----------------------:|
| 1M | 20.06 s (3 fulls, 30 nursery pauses) | 7.38 s | **2.72x** | 1.69 / 1.40 GB |
| 2M | 40.57 s (4 fulls, 61 nursery pauses) |14.92 s | **2.72x** | 3.04 / 2.81 GB |

6.0x -> 2.7x at ~vanilla memory (+20% for the larger nursery). Residual at 1M
(~12.7 s): promotion copy ~10 s (the 5.6x/KB term), mutator ~4 s, fulls ~3 s —
these need code, not knobs.

Reading:
- **Nursery size and UP-oldify are amortization levers, not fixes.** Bigger
  nursery cuts collection COUNT (fixed per-GC root/stack scan, worker
  park/wake), not copy VOLUME. Stacked, 256 MB + UP-oldify ~ 24 s, still
  ~3.4x, at low RSS.
- **Immix (non-moving) closes the TIME gap to ~1.2-1.3x but costs 3-4x the
  MEMORY.** It marks in place (copied=0), so it is fast, but non-moving means a
  looser heap; the copying that makes Bactrian slow is also what lets a moving
  collector pack tight. Classic space/time trade. (Immix also SIGSEGVs at a
  very tight 2 GB heap — separate bug.)
- **StickyImmix would be the ideal fix** — generational structure with in-place
  young marking = Immix's speed AND generational compactness — but it panics
  under the native binding (`epilogue.rs:11`, stage-not-drained assertion).

## Recommendation

Three levers, in order of payoff:
0. **Pacing — measured 15.5 s / 44% of the gap from one knob.** The bytes
   backstop (`cadence_budget_bytes`, 512 MiB of nursery allocation per full)
   is denominated in the wrong quantity: allocation volume, not survivors or
   headroom. Re-denominate it in promoted (mature-growth) bytes and/or scale
   it by the previous full's yield (a full that reclaimed ~nothing should
   lengthen the cadence, not repeat), or pace against headroom like vanilla's
   slices. Today: `MMTK_FULL_GC_CADENCE=<large>` disables it (42.7 -> 26.8 s).
   Cheapest fix; no architectural change. CLBG spot-check at T=1, 192 MiB
   pinned, backstop default -> off: binarytrees 5.32 -> 4.88 s (13 -> 8 fulls,
   RSS 183 -> 179 MB), kb / fragmed / mature_mutation unchanged (wall, RSS,
   fulls). At a pinned heap the margin law + heap limit already cap RSS, so
   the backstop only added fulls. STILL TO CHECK before changing the default:
   the DYNAMIC-heap configuration, where the backstop is what bounds a churn
   workload's growth between fulls.
1. **Promotion copy (27%)**: 5.6x per KB vs vanilla. Real fix is StickyImmix under the native binding, so
   Bactrian-family collectors can mark surviving young objects in place instead
   of evacuating them. Gets Immix's speed without Immix's memory. Blocked on the
   `epilogue.rs:11` panic — file it.
2. **Interim / heuristic**: detect sustained near-100% nursery survival and
   either widen the nursery aggressively (256 MB gave -30%) or route the
   profile to Immix, accepting the memory trade.
3. Keep UP-oldify on (free 11%).

## Bugs surfaced (file on the fork)

- StickyImmix native: GC-worker panic at `util/epilogue.rs:11` on sedlex
  (blocks the general fix above).
- Immix native: SIGSEGV (rc=139) at a very tight pinned heap (2 GB / ~1.4x
  live) on sedlex; fine at >= 4 GB.

## Still to do

- perf stat (cycles, instr, LLC/L1/dTLB misses) + flamegraph, vanilla vs
  Bactrian, to confirm the evacuation path at instruction level — CONFIRMATORY.
  Blocked on `sudo sysctl kernel.perf_event_paranoid=-1`.
- Once StickyImmix is fixed: re-measure sedlex on it (expected: Immix-class
  time at Bactrian-class RSS) and check it against the rest of the panel.
