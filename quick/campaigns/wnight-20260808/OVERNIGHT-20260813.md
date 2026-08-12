# Overnight report — 2026-08-13 (round 30d; battery `wcomp8`)

Directives worked: (1) state the accepted overhead and investigate any D4
deviation above it — mature_mutation's 120MB flagged; (2) MMU curves for D3;
(3) fix fragmed's reclamation problem; (4) n16 stays default; UP-oldify
stays opt-in. Tree: fork `16505c123` + core `7ddf1ed2bf` (pushed, deployed).
Figures in `figs-v8/`; raw tables in `raw/wcomp8-tables.txt`. This
supersedes v6/v7 for the changed cells; v6's per-bench explanations
otherwise stand.

## The overhead accounting (now the doctrine, stated up front)

Expected Bactrian-over-vanilla RSS on any benchmark ≈ **25MB**: up to 16MB
of adaptive nursery (vanilla's minor heap is 2MB) + ~7–10MB of MMTk fixed
cost (measured cleanly on the zero-GC benches: nbody 9.7 vs 2.8MB). Every
bench is inside it except the two below — both were investigated tonight.

## mature_mutation's D4 excursion: found and fixed

**Mechanism (line-blind waste).** Its dead 24-byte cells sit interleaved
with live ones on the same 256-byte Immix lines. A line is only freed when
*nothing* on it is live, so the sweep reclaims nothing; worse, every
statistic Immix keeps (holes, line counts, block occupancy) reports the
space as *dense* — the waste is invisible to the round-29 fragmentation
trigger and to defrag's candidate selection alike. 6.6MB of live cells
pinned 120MB. Only the trace itself knows the truth.

**Fix (the `Gc.max_overhead` analog).** The major trace now tallies the
bytes it actually marks (`major_live_bytes`, one relaxed add per marked
object). After a monolithic Full's sweep, if reserved bytes exceed
marked-live by `MMTK_COMPACT_OVERHEAD_PCT` (default 100%), the next major
runs as a **compact-all Full**: every block is an evacuation candidate
(bounded by copy headroom — leftovers stay put, successive compactions
converge), and the freed blocks' pages are returned to the OS
unconditionally. Result: **D4 peak 120→68MB, steady ~57–72 sawtooth**
(fig4), fixed-heap RSS 111→77. bt/kb/sp fire it exactly zero times
(reserved ≈ marked-live on dense heaps).

**The honest cost.** matmut's D1 moves 1.77→**2.41×**: on this workload
every plain sweep is useless, so periodic whole-live evacuation is the only
reclaim — cycles vanilla doesn't need because its free-list sweep reclaims
each dead cell individually. This is the same regime difference fragmed
exposes (below), concentrated by the adversarial write pattern. The trade
is D4-doctrine-first, per direction.

**A lesson the battery taught twice (v7).** The reserved-vs-marked-live
ratio is only exact for monolithic Fulls; a concurrent cycle's post-sweep
reserved carries SATB floating garbage and window promotions the trace
tally can't see. An ungated law false-fired a 193ms compact-all into
bt@2M and drove fragmed to 11× — v8 gates the law to the Full regime and
both revert to clean numbers.

## fragmed: root cause fixed in staging, not yet default

The real fix is vanilla's regime: route the ≥2056B pretenured band to the
free-list mark-sweep space (`MMTK_MEDIUM_TO=freelist` — landed tonight,
**default OFF**). Mechanically it works (goldens pass; RSS dropped to
30MB, *below* vanilla's 45), but it is **unsound under concurrent
cycles**: the mark-sweep space's lazy sweep runs at block-acquisition time
using the in-flight cycle's *incomplete* marks and frees
not-yet-marked-but-live cells — reproduced as a marking quantum crashing
on a freed cell whose header had become a free-list link. The eager-sweep
alternative deadlocks under Bactrian's pause schedule. Groundwork landed
(allocate-black births in the free-list allocator; the band made visible
to pacing — it was invisible: 1 GC, 203MB); the sound design for the next
round is "mid-cycle block acquisition serves clean blocks only".
Until then fragmed reads **3.09× / 189MB** with the mechanism understood
and the fix staged.

## D3 — MMU curves added (fig7)

For every window length w: the worst-case fraction of that window the
program got to run. This is the latency view CDFs can't give (ten
back-to-back 5ms pauses and ten scattered ones have identical CDFs).
Reading v8: **@2M tracks vanilla's utilization curve from ~3ms windows on
kb and ~10ms on bt** (and bt@2M's max pause is 13.4ms vs vanilla's 14.9 —
below it); the n16 default is flat-zero until its pause scale (~50ms
minors / ~130ms Fulls) — the throughput mode's documented shape. CDFs
kept as the distribution view (fig3).

## v8 headline numbers (what changed vs v6)

| | v6 | v8 | why |
|---|--|--|---|
| geomean (11) | 1.22 / 1.19 oldify | 1.26 / 1.24 | matmut's compaction tax |
| geomean (original 8) | 1.06 / 1.05 | 1.06 / **1.04** | stable |
| matmut D1 | 1.77 | 2.41 | compaction tax (D4-first trade) |
| matmut D4 dyn | 120 flat | **68 peak / 57 steady** | the fix |
| matmut RSS @192 | 111 | 77 | same |
| fragmed | 3.06 / 189MB | 3.09 / 189MB | unchanged; fix staged |
| bt@2M max pause | 16.6 | **13.4** (vanilla 14.9) | clean cycles |
| attribution | 387→345 | 404→359 | live-tally adds ~15cy/obj to majors |

Everything else within noise of v6 (bt 1.26/1.16, kb 1.10/1.05, LU 1.14,
sp 1.05, matmul lottery ±5%, weak_memo 1.01/0.97, nbody/fannkuch/mandel
1.00).

## Corrections to the v6 report

- "32KB blocks are coarser than vanilla" — wrong: vanilla's pools are
  `POOL_WSIZE` = 4096 words = the same 32KB. The D4 floor is nursery +
  fixed cost + between-cycle garbage, not block granularity.
- "16MB dynamic-heap minimum" — it's **32MB** (`MMTK_MIN_HEAP_MB`,
  api.rs); the README said 16 and has been fixed. Because the 8MB
  mature-pressure floor paces cycles independently, this floor matters
  less than the nursery for small-live RSS.

## Open decisions (carried + new)

1. UP-oldify default — you said keep opt-in; done.
2. matmut's D1-vs-D4 dial: `MMTK_COMPACT_OVERHEAD_PCT` (100 = tonight's
   trade; 0 restores v6's D1 at 120MB RSS; higher = less compaction).
3. The freelist-band round (fragmed's real fix): clean-blocks-only
   acquisition design — propose as the next implementation round.
4. Heap-coupled nursery (the D5 lever from yesterday's discussion) —
   still queued behind this round.
