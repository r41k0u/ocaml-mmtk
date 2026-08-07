# Measuring the GC space-time shape: vanilla OCaml 5.5.0 vs Bactrian

**The question.** `MMTK_PLAN=Bactrian` re-expresses OCaml 5's collector
architecture inside MMTk (copying nursery; concurrently-marked, non-moving-ish
Immix mature; SATB; no read barrier). We do not require it to copy vanilla's
*implementation* — dedicated GC worker threads are fine. We require it to
occupy the same **space-time shape**. This document defines the shape's
dimensions, how each is measured identically on both runtimes, and shows the
measured gap. Companion figures live in this directory; every number behind
them is in `shape_summary.md`.

**Setup.** church: 2× Xeon Gold 5120, all runs pinned to the 14 physical cores
of socket 0 (`taskset -c 0-13` — one thread per physical core, inside one NUMA
node), `performance` governor, `perf_event_paranoid=-1`. Vanilla = pristine
released 5.5.0 (`f5238509d`). Operating point: Bactrian pinned at 192 MiB
(`MMTK_THREADS=1` sequential, `=domains` parallel) vs vanilla at
`space_overhead=500` — the iso-memory pairing derived from the D5 sweep.
Vanilla has no heap cap, so memory comparisons use *measured peak RSS*, never
the commanded heap.

## Dimensions and instruments

| dim | what is measured | vanilla instrument | Bactrian instrument |
|---|---|---|---|
| **D1** CPU budget | collector CPU `G` vs program CPU `W`; the fraction `G/(G+W)` | `runtime_events` spans (`EV_MINOR` + `EV_MAJOR_SLICE` + `EV_MAJOR_GC_STW`) — vanilla runs all GC *on* the mutator, so span time *is* collector CPU; total CPU from `getrusage` | named GC worker threads (`/proc/<pid>/task/*/stat` per-TID CPU) **plus** runtime-timed mutator-side GC (barriers, TLAB refills, LOS allocs; `MMTK_MUTATOR_GC_TIME`, park time excluded); cross-validated by perf hybrid attribution (worker-thread samples → G by identity, mutator samples → by symbol) |
| **D2** pacing | collections per unit allocation | `Gc.stat` counters (verified equivalent odometers) + in-mutator probe samples | `MMTK_VERBOSE` counts + probe samples |
| **D3** latency shape | stall distribution + MMU curve. A *stall* = interval in which the mutator makes no program progress | external `runtime_events` ring reader (per-span records; zero overhead — measured) | `MMTK_PAUSE_LOG` per-pause records (cross-validated against the summed total to 0.7%) |
| **D4** footprint | RSS over time | external `/proc/statm` sampler, 10 ms (identical both sides) | same |
| **D5** space-time curve | wall time vs measured peak RSS | sweep `OCAMLRUNPARAM o=` 40–500 | sweep `MMTK_HEAP_SIZE_MB` 64–1024 |
| **M1/M2** | the above across domain count (1–8) and the 8-bench workload panel | — | — |

**Key definitional choices, applied symmetrically.** Write barriers and
allocation slow paths count as collector work on both sides. Vanilla's
incremental major *slices* count as stalls (the mutator is not progressing,
which is what MMU measures) even though they are not stop-the-world. Multi-domain
stalls use the union across domains. Blocked (parked) time is wall, not CPU —
excluded from D1, captured by D3.

## Results (figures in this directory)

**D1** (`d1_cpu_budget.png`, `d1_gc_only.png`, `d1_hybrid_perf.png`):
where GC actually runs, Bactrian's collector CPU is close to vanilla's —
binarytrees G 1.73 vs 1.97 s (fraction 0.41 vs 0.54), kb 0.29 vs 0.19 — and the
two independent instruments agree (perf hybrid: 0.391/0.500, 0.160/0.136). The
persistent gap is **W**: the same program burns more CPU under Bactrian on
every allocating bench (binarytrees 2.54 vs 1.65 s).

**Counters** (`counters_panel.png`): the W gap is not extra work — instruction
ratios are ~1.0× (binarytrees 0.84×) while cycle ratios run 1.2–1.8×. Two
measured mechanisms: (1) *allocation-pitch set-aliasing* for large regular
objects — matmul at size 768 shows 12.3× LLC-loads, collapsing to 2.5× at size
800 with vanilla flat, the signature of bump allocation's regular pitch
conflicting in L2 sets; (2) *nursery reuse-warmth* — per-thread counters show
Bactrian's mutator executing the same instructions at IPC 1.86 vs ~2.4, equal
demand-LLC traffic, with page faults migrated wholesale to the GC worker:
vanilla re-bumps a warm 2 MiB arena, Bactrian streams a cold 64 MiB nursery.
These two want *opposite* nursery policies; that tension is the central
engineering problem.

**D2 + the pacing experiment** (`tweak_frontier.png`, from the powersave-era
run; shape/tweaks branch): stock-parity pacing is pure configuration
(`MMTK_NURSERY=Fixed:2MiB` + `MMTK_FULL_GC_CADENCE`) — 1867 collections vs
vanilla's 1839 — but costs 5–8× wall, because the per-minor floor is ~7.5 ms vs
vanilla's 0.63 ms (~12×). The floor, not the trigger, blocks D2 matching.

**D3** (`d3_cdf_*.png`, `d3_mmu_*.png`): the shapes are *opposite*. Vanilla
stalls thousands of times briefly (binarytrees: 3553 stalls, MMU@100ms 0.06);
Bactrian stalls ~60 times, concentrated (MMU@100ms 0). kb separates them:
vanilla MMU@10ms 0.76 vs Bactrian 0.00. Neither dominates; the window decides.

**D4/D5** (`d4_rss_*.png`, `d5_*.png`): vanilla's footprint is a staircase and
its space-time curve slopes (more memory → real speedup); Bactrian rises with
per-collection spikes and plateaus above ~180 MiB (extra memory buys nothing —
its triggers cannot spend it).

**M1** (`m1_scaling.png`): Bactrian beats vanilla wall-clock at d=1–2, ties at
d=4, and collapses at d=8 (17.0 vs 5.0 CPU-s) — domains + workers
oversubscribing 14 cores; a worker-cap policy fix.

## Known limitations

Vanilla's own write-barrier cost sits outside its spans (small; favours
vanilla's W). Thread-CPU sampling loses up to one 20 ms interval per thread.
The probe resolves pacing (D2) but not stalls on coarse-grained workloads —
D3 uses the authoritative streams instead. Single host; laptop results were
additionally confounded by a hybrid-core `powersave` governor and are
superseded by this campaign.
