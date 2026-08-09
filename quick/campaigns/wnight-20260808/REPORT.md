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

---

# Addendum — rounds 5-6 (same day): the residual, named and bounded

**Verdict counter: `resource_stalls.sb` (store buffer full).** The remaining
cycle-ratio gap on every allocating bench is one mechanism:

| bench | vanilla SB-full | Bactrian SB-full | cycle ratio |
|-------|----------------|------------------|-------------|
| LU_decomposition | 1.4% | **14.9%** | 1.38 |
| spectralnorm | 0.1% | **7.6%** | 1.14 |
| binarytrees | 1.1% | **4.4%** | 1.12 |

LU's profile is >85% the *same three OCaml functions* on both runtimes — the
same code, slower, waiting on stores. Allocation stores into the cold 64 MiB
nursery stream must fetch each line from DRAM/L3 before retiring (RFO); the
56-entry store buffer fills and the pipeline stalls. Vanilla's 2 MiB reused
arena keeps the write frontier L2-resident, so its stores retire instantly.
(Earlier `stalls_mem_any` numbers missed LU because that counter only sees
stalls with pending *loads*.) See `fig6_storebuffer.png`.

**Negative result — TLAB prefetch.** Warming each fresh 32 KB block with
`prefetchw` at refill HURTS everywhere (LU +24%, kb +7%, bt +4%): burst
prefetch floods the fill buffers. Knob `MMTK_TLAB_PREFETCH` kept, default off.

**Worker cap (d=8), measured:** T=4 gives 2.17s vs T=8's 2.42s
(par_binarytrees, 14 cores; vanilla 1.27s). Policy: **domains + workers ≤
physical cores.** Recall Bactrian *beats* vanilla at d=1-4 (0.83-0.84×).

**Jitter entropy: 6 bits confirmed optimal** (7/8 bits regress on matmul).

## The honest tolerance statement

With placement (jitter), THP, and the worker cap banked, the remaining
1.1-1.4× cycle ratios are **not incidental overhead — they are the structural
cost of a decoupled streaming nursery**, and no environment knob measured
tonight moves them (nursery sweep, prefetch, LOS, entropy bits all tested).
Reaching cycle-ratio ≈ 1 on allocating benches requires the small-warm-nursery
architecture, which requires collections ~50× cheaper per occurrence:
premature-promotion handling, park/futex churn (56 → 20.5k calls), and packet
overhead. That is the next engineering phase, in mmtk-core scheduling — with
this campaign as its measurement baseline.

---

# Addendum 2 — the work-only verdict and the pacer fix

**Operating metric refined:** W compared as *work-only* on both sides —
vanilla's inline GC excluded by symbol classification (gcsplit, symmetric
judgment calls), Bactrian's worker counted G by identity and its mutator
classified by symbol.

## W-instruction parity: achieved

| bench | W-ins ratio | W-cyc ratio | vanilla G-cyc | Bactrian G-cyc |
|-------|------------|-------------|---------------|----------------|
| binarytrees | **1.022** | 1.355 | 5.72G | 5.12G |
| kb | **1.022** | **1.039** | 0.57G | 0.82G |
| LU (4 MiB nursery) | **1.042** | 1.110 | 0.01G | 0.76G |
| spectralnorm (8 MiB nursery) | **1.028** | **1.076** | 0.00G | 0.32G |
| matmul | **1.005** | 1.311 | 0.02G | 0.04G |

The mutator executes vanilla's work instruction-for-instruction (1.005–1.042).
kb and spectralnorm are at W-cycle parity; note binarytrees' collector is now
*cheaper* than vanilla's in cycles.

## The architectural change that unlocked it

The GH#5 full-GC backstop was **re-denominated from minors to allocation**
(commit `78ab9698a`, binding-side, LXR-inert — see NOTES.md): the old
8-minors-per-domain law forced a whole-heap collection every ~16 MiB allocated
at a 2 MiB nursery — a manufactured full-GC storm (186 fulls vs 6; 141G vs 46G
cycles). With the new law, small nurseries became usable, which erased LU's and
spectralnorm's store-buffer stalls (SB-full 1.13G → 0.08G cycles) — those two
benches' W-cycle ratios fell to 1.11 / 1.08.

## Remaining W-cycle offenders, named

- **binarytrees 1.355** — store frontier at the 64 MiB nursery. A small warm
  nursery is blocked by *real* premature promotion (live survivors), not by
  the pacer anymore. The fix is nursery **aging** (survive N minors before
  promotion) — Bactrian-plan-local, multi-session scale, LXR untouched.
- **matmul 1.311** — residual conflict-miss stalls after jitter (LLC-loads
  69M vs 57M; 6 entropy bits measured optimal, 7/8 regress).
- LU 1.110 — post-GC cache-warmth loss across 3282 minors (per-minor cost).

## Addendum 3 — adaptive marking (second architectural change)

Concurrent marking of a small live set was measured to cost the mutator more
(shared-LLC interference + SATB barrier activity: 7.84G→6.78G cycles,
14.17G→13.40G instructions when disabled) than it saves in pause time.
Bactrian now runs a requested major cycle STW when the mature size is below
`MMTK_CONC_MARK_MIN_MATURE_MB` (default 256 MiB; 0 = always-concurrent).
Large live sets — where pauses matter — keep the concurrent path, so the
thesis is intact. Plan-local in the mmtk-core fork (`bactrian/global.rs`,
commit `6d7588c4c2`); LXR does not consult this path.

**W-cycle scoreboard after both architectural changes** (pacer + adaptive
marking; W-instructions 0.98–1.04 everywhere):

| bench | W-cyc before tonight | now | remaining mechanism |
|-------|---------------------|-----|---------------------|
| binarytrees | 1.355 | **1.239** | store frontier at 64 MiB (aging project) |
| kb | 1.039 | ~1.04–1.12 (noise band) | — near parity |
| LU (4 MiB) | 1.110 | 1.110 | per-minor warmth + L2-streaming floor |
| spectralnorm (8 MiB) | 1.076 | 1.076 | near parity |
| matmul | 1.311 | 1.311 | residual conflict stalls post-jitter |

## Addendum 4 — survivor aging: tried, correct, and a measured negative

`MMTK_NURSERY_AGE=1` (experimental, default off) implements survive-one-minor
aging via a semispace aged pair inside the Bactrian plan (mmtk-core fork
`bdcd5356f9`). It is correct on non-mutating workloads (outputs identical;
OFF-mode byte-identical; a latent finalizer-processor unsoundness for movable
young survivors was found and fixed in shared code behind a defaulted trait
method — LXR and stock plans unchanged).

Measured on binarytrees-20 (church): default nursery 12.10G→12.46G cycles;
4 MiB nursery 31.09G→33.12G — full GCs drop (22→14) but objects copied rises
34.5M→50.9M. **Negative**: bt's survivors live for a whole depth-class
iteration, far beyond one aging step, so aging double-copies its entire
promoted volume.

The refined conclusion for bt's remaining W-gap (1.239): vanilla affords its
tiny cache-warm allocation window because its **mature reclamation is
incremental**, making premature promotion cheap — not because it avoids
promotion. The next structural lever for bt-class lifetimes is incremental/
concurrent mature-sweep economics, with aging kept for medium-lifetime
workloads once the documented remset hole is closed (see NOTES).

## Addendum 5 — W-cycle endgame: parity via vanilla's own methodology

The 32KB bump-allocation granule was the last structural offender: its
per-block tail-skip phase-locked medium-object cache-set placement (matmul's
739/903M LLC regimes) and its refill rate taxed every allocating bench.
Raising the granule (`MMTK_BUMP_BLOCK_KB`, default now 512) puts matmul on
vanilla's exact LLC floor (57M / 64M) and refunds 2–10% of mutator cycles
panel-wide. Two upstream mmtk-core bugs fixed en route (marksweep-as-nonmoving
release path; granule tunability added).

**Final W-cycle scoreboard** (vanilla methodology intact — copying nursery,
allocation-paced fulls, continuous placement): kb **0.98**, binarytrees@16M
**1.009 (parity, 3 reps)**, spectralnorm 1.05, matmul 1.15, binarytrees-default
1.16, LU 1.16. Remaining work is G-side only (per-slot trace cost, lazy mature
reclamation) to make the bt W-parity nursery config G-affordable.

## Addendum 6 — combined D1 panel (post G-slim rounds 14–16)

Symbol-split hybrid attribution, cycles (G), all 8 benches, current defaults
(granule 512, jitter, THP, pacer, adaptive marking, phase-dynamic trusted
loads, gated copy telemetry):

| bench | vanilla W / G (D1) | Bactrian W / G (D1) | W-ratio |
|-------|--------------------|---------------------|---------|
| binarytrees | 5.81 / 5.70 (0.495) | 6.95 / 4.62 (**0.399**) | 1.20 |
| binarytrees @16M nursery | " | 6.42 / 12.00 (0.651) | **1.10** |
| nbody | ~0 G | ~0 G | 1.00 |
| fannkuchredux | ~0 G | ~0 G | 1.03 |
| spectralnorm | 4.88 / 0.00 | 5.21 / 0.09 | 1.07 |
| mandelbrot | ~0 G | ~0 G | **0.97** |
| matrix_multiplication | 4.62 / 0.01 | 5.71 / 0.04 | 1.24 |
| LU_decomposition | 5.38 / 0.00 | 6.50 / 0.27 | 1.21 |
| kb | 3.92 / 0.59 (0.131) | 4.04 / 0.75 (0.157) | 1.03 |

- bt default: Bactrian's GC fraction 0.399 vs vanilla 0.495 — the D1 shape
  favours Bactrian at near-equal totals (11.6 vs 11.5G).
- bt@16M: the W-dial row — W-ratio 1.10 on this instrument (1.02 pt-attach;
  the two instruments bracket it), G 12.0G pending the UP-trace slim.
- matmul/LU's 1.21-1.24 on this instrument vs 1.15-1.16 pt-attach: same
  ±0.05 instrument spread seen all campaign; mandelbrot runs below vanilla.
