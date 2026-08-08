# W-night report — 2026-08-08 (church)

**Goal (operating decision):** get Bactrian's *work* time (W — mutator cycles)
to parity with vanilla; G may differ in seconds *and* in collection count.
Equivalently: instruction ratio ≈ 1 (was already true) and cycle ratio → 1.

**Method:** iterative fix→gate→measure loops on church (2×Xeon Gold 5120,
performance governor, cores 0-13, `setarch -R`), heap 192 MiB vs vanilla
`o=500` (phase3 iso-memory point), `MMTK_THREADS=1`, 3 reps/cell (medians;
rep variance 0.15%). Instruments: `perf stat` whole-process + per-thread
attach (mutator vs `mmtk-gc-worker`), `threadcpu` corrected-W, `strace -c`,
`perf record` profiles. Raw data for all five rounds in `raw/`.

## What changed in Bactrian (now default, commit `683521d7a`)

1. **Allocation-pitch jitter, default ON (6 bits).** Bump allocation placed
   large regular objects (matmul's 6 KB rows) at a fixed pitch that aliases
   L2 sets: 739M LLC-loads vs vanilla's 57M at size 768. A 0..63-line dead
   filler before each ≥2 KB allocation removes it (69M) and improves the
   benign-pitch case too (mm800: 140M → 72M). The v1 pad (8-128 B) had
   *created* new near-alignments at size 800 — entropy must be line-granular.
   `MMTK_ALLOC_JITTER=0` disables, `2..8` picks bits.
   **LOS routing was tried first and is anti-productive** (906M LLC-loads):
   page-aligned placement has *zero* low-bit entropy — it is the disease.
2. **Transparent hugepages, default ON.** Uniform 2–3.5% cycle win
   (bt 13.10→12.81G, kb 5.43→5.28G, LU 7.64→7.38G) by cutting dTLB churn
   from the streaming nursery (Bactrian dTLB-store misses were 100× vanilla's
   on LU). Explicit `MMTK_TRANSPARENT_HUGEPAGES` still honoured.

Output-parity gates passed on the full 8-bench panel and `par_binarytrees`
d=4; jitter self-verifies via `[mmtk] jitter fillers: N` at exit.

## Certification (round 4, medians of 3)

| bench | cycle ratio stock | cycle ratio new | ins ratio | wall v | wall new |
|-------|------------------|-----------------|-----------|--------|----------|
| binarytrees | 1.138 | **1.121** | 0.832 | 3.64s | **3.55s** |
| nbody | 1.000 | 1.004 | 1.000 | 2.11s | 2.11s |
| fannkuchredux | 1.027 | 1.028 | 1.000 | 3.33s | 3.42s |
| spectralnorm | 1.166 | 1.143 | 1.036 | 1.54s | 1.76s |
| mandelbrot | 0.981 | **0.982** | 1.001 | 1.77s | **1.73s** |
| matrix_multiplication | 1.914 | **1.410** | 1.019 | 1.48s | 2.09s |
| LU_decomposition | 1.430 | 1.377 | 1.059 | 1.69s | 2.33s |
| kb | 1.203 | 1.174 | 1.029 | 1.42s | 1.68s |

par_binarytrees (heap 448, workers=domains): Bactrian **0.83–0.84× vanilla's
wall at d=1,2,4** (faster); d=8 collapses (1.88×) — the known oversubscription
problem (8 domains + 8 workers on 14 cores), now clearly a *policy* item.

Mutator-only W (per-thread attach): bt 7.9G vs vanilla's ~5.2G W-share
(1.5×); kb ≈ 1.1×. The whole-process ratios above understate W-parity progress
on bt because Bactrian's G is *smaller* than vanilla's.

## What we learned (the night's findings)

- **F1 — instruction ratio 0.82 on bt is real and good.** Validated under
  single-core, SMT-pair, unpinned, and drift re-passes (0.824–0.855).
  Closure: Bactrian = 14.2G program + 10.6G worker; vanilla = same ~14G
  program + ~16G *inline* GC. Bactrian's collector is instruction-cheaper
  (57 big collections vs ~1800 small ones).
- **F2 — the residual W-tax is STORE-side, one mechanism across benches.**
  Bactrian's mutator loads hit L1 at 98.9% (L2/L3 hits ≈0) — pointer chasing
  and prefetch are fine — yet memory-stall cycles double (16.4% vs 8.3% on
  bt; IPC 1.92 vs 2.62). Bump stores into never-touched cold lines drain at
  RFO latency through the store buffer, invisible to load counters. LU shows
  the DRAM-level version: 155M demand misses vs vanilla's 0.2M. Vanilla is
  immune because its 2 MiB arena keeps the write frontier L2-resident.
- **F3 — warmth cannot be bought with a small nursery today.** bt nursery
  curve 64→2 MiB: wall 3.6s→27.4s, instructions 25G→240G, fulls 6→186.
  Premature promotion fills the mature space with garbage → full-GC storms;
  park/wake futex traffic scales 56→20.5k calls. LU (zero survivors) proves
  the marginal cost of an *empty* collection is only ~113 µs — the "floor"
  is copy-cost × survivors, not a constant.
- **F4 — the promotion-scatter hypothesis is refuted** (loads are L1-clean);
  deprioritized behind the store-frontier work.

## Engineering plan (ranked, evidence-linked)

1. **Store-frontier warmth** — the only remaining W mechanism that matters:
   TLAB block-reuse order (hand back warm blocks first), prefetchW-ahead on
   refill, non-temporal fills for large objects. Target: bt mutator
   stalls_mem_any 1.42G → vanilla-like share (~0.7G ≈ 0.7G cycles ≈ the
   whole remaining bt W gap).
2. **Worker cap policy for d≥8** (domains+workers ≤ physical cores) — erases
   the only parallel regression; pure config.
3. **Cheap-collection work** (packet overhead, premature-promotion handling)
   — unlocks smaller nurseries longer-term, per F3.
4. matmul/LU's last ~1.35×: partially store-frontier (see 1); re-measure
   after.

## Figures

- `fig1_ratios.png` — cycle+instruction ratios, stock vs new defaults
- `fig2_matmul_llc.png` — the pitch-aliasing story incl. the LOS dead end
- `fig3_nursery.png` — bt premature-promotion catastrophe; LU store frontier
- `fig4_stalls.png` — the store-stall verdict (stalls up, loads clean)
- `fig5_m1.png` — M1 scaling with new defaults (wins d=1-4, d=8 policy item)
