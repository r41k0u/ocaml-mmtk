# BACTRIAN-CHANGES.md — policy changes made during the W-parity campaign

Chronological log of every **policy / behavioural** change to the Bactrian plan and its
runtime binding between 2026-08-07 and 2026-08-08, with the measurement that motivated
each one and the measurement that certified it. Instrumentation-only changes are listed
separately (§3) so they are not mistaken for policy.

Sources: `gc/mmtk/SHAPE.md` (rounds 1–8), `gc/mmtk/NOTES.md` (two dated 2026-08-08
entries), this directory's `REPORT.md` + addenda 1–3, and the commits on
`shape/tweaks` (`c225f01d1` … `23e106d86` plus the submodule bump `a42cd306c`).

## 1. Goal and measurement definition

**Goal (operating decision, 2026-08-08):** bring Bactrian's *work* time to parity with
stock OCaml 5.5. `W` — mutator cycles spent on the program's own instructions — must
approach vanilla's; `G` may differ in seconds **and** in collection count. Bactrian is
architecture-matched, not implementation-matched, so a differing `G` is by design; a
differing `W` is a tax on the program and is not.

**How W is measured.** Work-only, classified symmetrically on both runtimes via `gcsplit`
symbol classification, with barriers and allocation slow paths counted as `G` on *both*
sides (so jitter fillers and TLAB refills are charged to the collector, as vanilla's inline
GC symbols are). On Bactrian the attribution is **hybrid**: samples on `mmtk-gc-worker`
threads are `G` by thread identity, mutator samples classify by symbol. Flat symbol
classification alone undercounts `G` — it read `G/(W+G)` = 0.25 on Bactrian/binarytrees
against `threadcpu`'s 0.42, because GC copying runs through libc `memmove`/`memset`, which
a flat symbol map files under `W`. Hybrid yields 0.39 (bt), agreeing with 0.42.

**Rig.** church (2×Xeon Gold 5120, 56 threads), `taskset` cores 0-13 = one thread per
physical core of socket 0, `performance` governor, `setarch -R`, heap 192 MiB against
vanilla `o=500` (iso-memory), `MMTK_THREADS=1`, 3 reps/cell, medians; rep variance 0.15%.

### Before / after headline

These two tables are **different metrics at different operating points** and must not be
subtracted from one another — the first is whole-process (mutator + collector) at stock
defaults before the campaign, the second work-only, with LU and spectralnorm at pinned
small nurseries that only became usable after the pacer change (§2d).

*Before — whole-process cycle ratio (Bactrian / vanilla), pre-jitter/pre-THP, default
configs (REPORT round 4, "cycle ratio stock"):*

| bt | nbody | fannkuchredux | spectralnorm | mandelbrot | matmul | LU | kb |
|---|---|---|---|---|---|---|---|
| 1.138 | 1.000 | 1.027 | 1.166 | 0.981 | 1.914 | 1.430 | 1.203 |

*After — W-cycle and W-instruction ratios, work-only, hybrid attribution (SHAPE rounds
7–8). The work-only re-profile covered these five benches only; nbody, fannkuchredux and
mandelbrot were not re-profiled because they were already at whole-process parity above
(1.000 / 1.027 / 0.981) — they are absent, not dropped:*

| bench | config | W-ins ratio | W-cyc ratio |
|---|---|---|---|
| binarytrees | stock defaults | 0.978 | **1.239** |
| kb | stock defaults | 1.022 | **~1.04–1.12** (sampled-split noise band) |
| LU_decomposition | `Fixed:4MiB` | 1.042 | **1.110** |
| spectralnorm | `Fixed:8MiB` | 1.028 | **1.076** |
| matmul | stock defaults | 1.005 | **1.311** |

W-instructions land at 0.98–1.04 across the panel: the mutator now executes vanilla's
work instruction-for-instruction. binarytrees' collector is also *cheaper* than vanilla's
in cycles (G-cyc 5.08 G vs 5.72 G).

## 2. Policy changes, in order

Rows are lettered as in the change brief; note that **(e)**, being documentation-only,
was recorded at 13:22, ~24 minutes *before* (d).

| # | date | change | where (file · sha) | default + knob |
|---|---|---|---|---|
| a | 08-08 04:57→05:42 | allocation-pitch jitter (v1→v2→v3, then default ON) | `runtime/mmtk.c` · `c225f01d1`, `49ffd7e58`, `154de2d31`, `683521d7a` | **ON, 6 bits**; `MMTK_ALLOC_JITTER` (`0` off, `1`=5 bits, `2..8` explicit) |
| b | 08-08 05:42 | transparent hugepages default ON | `gc/mmtk/binding/src/api.rs` · `683521d7a` | **ON**; `MMTK_TRANSPARENT_HUGEPAGES` honoured when set |
| c | 08-08 13:14 | TLAB prefetch-on-refill (negative result) | `runtime/mmtk.c` · `cea35bddd` | **OFF**; `MMTK_TLAB_PREFETCH` |
| d | 08-08 13:46 | full-GC backstop re-denominated: bytes, not minors | `gc/mmtk/binding/src/collection.rs` · `78ab9698a` | 8 × 64 MiB × ndomains; `MMTK_FULL_GC_CADENCE` (minor count) overrides |
| e | 08-08 13:22 | worker-cap policy for d≥8 (documented, no code) | `SHAPE.md` · `efdc6b5f4`; REPORT addendum 1 | policy only; `MMTK_THREADS` (default = nproc) |
| f | 08-08 14:05 | adaptive marking — STW-mark small live sets | mmtk-core fork `src/plan/concurrent/bactrian/global.rs` · `6d7588c4c2`, bumped by `a42cd306c`, documented `23e106d86` | threshold **256 MiB**; `MMTK_CONC_MARK_MIN_MATURE_MB` (`0` = always concurrent) |

### (a) Allocation-pitch jitter — default ON at 6 bits

**Problem.** Bump allocation places large regular objects at a perfectly regular pitch,
which aliases L2 sets at near-power-of-two sizes. matmul's 6 KB rows at size 768: 739 M
LLC-loads against vanilla's 57 M, whole-process cycles 8.70 G vs 4.56 G. A size sweep
confirmed the mechanism — vanilla stays flat while MMTk collapses (768 → 12.5×,
770 → 5.6×, 800 → 2.5×).

**What it does.** Before every ≥2 KB bump allocation, allocate a dead `Abstract_tag`
filler (never scanned, immediately garbage) whose length is drawn from a deterministic
xorshift64\* — no clock, so runs stay reproducible. Successive pads accumulate, so
absolute object offsets decorrelate as a random walk. Three revisions, each fixing a
measured defect in the one before:

- **v1 `c225f01d1`** — pad of 1..16 words (8–128 B). Removed mm768's excess (739 M →
  74 M) but **regressed the benign pitch at 800** (140 M → 217 M): sub-2-line entropy
  breaks exact alignment while manufacturing new *near*-alignments.
- **v2 `49ffd7e58`** — line-granular: pad = 1 + 8k words, k ∈ 0..31, i.e. 32 L2 sets.
- **v3 `154de2d31`** — parametric entropy bits (2..8). mm768's post-v2 residual still
  tracked the remaining LLC-load excess (82 M vs vanilla 57 M) with L1 misses identical,
  so 5 bits removed most but not all of the aliasing; parametric bits let the panel find
  the knee. **`683521d7a`** then set the default ON at 6 bits (0..63 lines).

**Certified effect.** matmul-768 LLC-loads 739 M → 69 M (vanilla 57 M), whole-process
cycles 8.7 G → 6.4 G; whole-process ratio 1.914 → 1.410. The benign case improves too
(mm800 140 M → 72 M). Neutral on benches with no large regular allocations — fillers only
precede ≥2 KB allocations. 6 bits measured optimal; 7 and 8 regress on matmul. Output
parity gates passed on the full 8-bench panel and `par_binarytrees` d=4.

**LXR compatibility.** Lives on the shared runtime allocation path (`runtime/mmtk.c`),
so it is plan-agnostic — no LXR-specific gating, and no LXR-specific behaviour. The
**LOS-routing dead end that motivated it** is in §4.1.

### (b) Transparent hugepages, default ON

**Problem.** dTLB churn from the streaming nursery — Bactrian's dTLB-store misses on LU
were ~100× vanilla's (3.0 M vs 0.03 M). **What it does:** `mmtk_ocaml_init` sets
mmtk-core's `transparent_hugepages` option to `true` when `MMTK_TRANSPARENT_HUGEPAGES` is
unset; `madvise`-based, a no-op off Linux.

**Effect.** Uniform 2–3.5% cycle win: bt 13.10 G → 12.81 G, kb 5.43 G → 5.28 G,
LU 7.64 G → 7.38 G. THP together with an 8 MiB nursery took LU to 7.00 G with
cache-misses erased (155 M → 1.0 M). **LXR compatibility:** a builder-level option set
before plan construction — applies to every plan alike; not gated, not LXR-specific.

### (c) TLAB prefetch on refill — negative result, knob kept default-off

**Hypothesis.** Round 3b named the residual W-tax as *store*-side: the mutator's loads
hit L1 at 98.9% (`mem_load_retired` L1hit 3.69 G, L2hit 0.04 G, L3hit ≈ 0), yet
`cycle_activity.stalls_mem_any` = 1.42 G, 18% of mutator cycles. Bump stores into
never-touched cold lines drain at RFO latency through the store buffer, invisible to load
counters. Warming the fresh block with write intent ought to help.

**What it does.** On TLAB refill, `prefetchw` the block **top-down** (OCaml bumps
downward from `young_end`): the top 1 KiB into L1 (locality 3), the remainder into L2
(locality 2).

**Effect — it hurts everywhere**: LU 7.38 G → 9.14 G, kb 5.24 G → 5.62 G,
bt 12.98 G → 13.46 G. Burst prefetch floods the fill buffers. The knob is retained for
future re-measurement but ships **off**. Runtime allocation path, so plan-agnostic — off
by default for every plan.

### (d) Full-GC backstop re-denominated from minors to allocated bytes

**Problem.** The GH#5 backstop forced a full GC "every 8 minors per domain", making
forced-full frequency scale **inversely** with nursery size. At `MMTK_NURSERY=Fixed:2MiB`
that is a whole-heap collection every ~16 MiB allocated — a manufactured full-GC storm:
**186 fulls on binarytrees-20 where the default config does 6**, and 141 G cycles against
46 G with the storm suppressed. Every small-nursery experiment was measuring this
artefact rather than the nursery.

**What it does.** The backstop is now denominated in nursery bytes collected: a full is
forced after **8 × 64 MiB × ndomains** of nursery allocation, whatever the nursery size,
reproducing the GH#5-validated timing at the default config exactly and nursery-invariant
elsewhere. This matches vanilla's own allocated-words pacing law.

**Effect.** Default-nursery behaviour verified byte-identical (13 GCs / 1 full on bt-18);
`Fixed:4MiB` drops from ~26 forced fulls to 4 (mature pressure only). Downstream this is
what unlocked the round-7 W table: with small nurseries usable, LU's and spectralnorm's
store-buffer stalls were erased (SB-full 1.13 G → 0.08 G cycles) and their W-cycle ratios
fell to 1.110 and 1.076. `MMTK_FULL_GC_CADENCE` (a minor count) remains the explicit
experiment override; when set, the old minor-denominated law applies.

**LXR compatibility.** The whole trigger block is gated on `plan.generational()`; LXR
returns `None` there, so the path is **inert** for it — LXR reclamation stays RC-driven
and must never be forced through this path.

### (e) Worker-cap policy for d≥8 — a documented policy, not a code change

**Problem.** At 8 domains on 14 physical cores, 8 domains + 8 workers oversubscribe the
machine. The 2026-08-07 campaign measured d=8 at wall 2.6 s and CPU 15–17 s against
vanilla's 1.79 s / 7.1 s — the only parallel regression on the panel.

**Measured policy.** `par_binarytrees` d=8 on 14 cores: **T=4 → 2.17 s vs T=8 → 2.42 s**
(vanilla 1.27 s); T=4–6 optimal. The rule is **domains + workers ≤ physical cores**.
For contrast, Bactrian *beats* vanilla at d=1–4 (0.83–0.84× wall).

**Status.** No code was changed — this is recorded as harness/deployment policy, set via
`MMTK_THREADS` (default remains mmtk-core's `nproc`). Autoscaling the worker pool against
the live domain count is left as future work. LXR compatibility: N/A, no code change.

### (f) Adaptive marking — STW-mark small live sets

**Problem.** A concurrent marker streaming a *small* live set through the shared LLC while
the mutator runs costs more in mutator stalls and SATB barrier activity than it saves in
pause time. Measured on binarytrees-20 (~100 MB live, 1 worker): with marking forced STW,
the mutator drops from **7.84 G → 6.78 G cycles and 14.17 G → 13.40 G instructions**; the
instruction fall is the SATB barrier work disappearing from the marking windows.
Whole-process 11.87 G against stock OCaml's 11.5 G.

**What it does.** In the `Pause` decision in `bactrian/global.rs`, a requested major cycle
runs as `Pause::Full` when the mature (Immix) reserved size is below
`MMTK_CONC_MARK_MIN_MATURE_MB` (default **256 MiB**; `0` restores always-concurrent).
Large live sets — where pauses actually hurt — keep the concurrent path, so Bactrian's
thesis is intact; small ones stop paying LLC interference for pause relief they do not
need.

**Effect (certified, round 8).** binarytrees W-ins **0.978**, W-cyc **1.355 → 1.239**,
G-cyc 5.08 G against vanilla's 5.72 G. kb read 1.117 this round against round 7's 1.039;
SHAPE treats 1.04–1.12 as the sampled-split noise band rather than a regression.
NOTES' pre-certification estimate ("W-cycle ratio ~1.36 → ~1.15 estimated") was
**superseded** by this re-certification — 1.239 is the number of record. Outputs
identical; `BACTRIAN_TRACE` shows 7× `Full` at the default threshold against 7×
`InitialMark`/`FinalMark` at threshold 0 on binarytrees-20.

**LXR compatibility.** In the mmtk-core fork, but strictly **Bactrian-plan-local** — the
`Pause` decision in `bactrian/global.rs` plus a file-local helper, 32 lines. LXR does not
consult this path. `BACTRIAN_NO_CONCURRENT` retains its unconditional-bisection meaning.

## 2b. Policy changes, 2026-08-10 session (after the list above)

- **Max_young_wosize pretenuring — DEFAULT ON for Bactrian.** The >=2056B band is born
  in the mature Immix space (NonMoving-semantic remap to a reserved plan-local
  ImmixAllocator; unlog-at-birth; allocate-as-live in marking windows). This is stock's
  placement law for the band (shared_heap.c pools/malloc), so it removes a vanilla-vs-
  Bactrian difference rather than adding one. `MMTK_MEDIUM_NONMOVING=0` reverts.
  Resolves the matmul residual (previous section 5): matmul default 1.03x vanilla,
  nursery-independent 1.05-1.08x, LLC-loads at the 57-58M floor.
- **Overflow-block line-phase rotation** (mmtk-core, `MMTK_OVERFLOW_PHASE_LINES=16`,
  mutator allocators only): fresh Immix overflow blocks start a rotating number of
  lines in, replacing the 32KB re-alignment that phase-locked same-sized medium
  streams (904M/205M LLC-load regimes -> 58M). Allocator-internal scaffolding standing
  in for glibc-arena contiguity.
- **Remset immediate filter**: caml_initialize / write_barrier's generational half skip
  values that are not blocks — stock's own ref-table filter. Kills per-slot remset
  buffering on born-mature immediate-array inits (46MB retained modbuf on matmul;
  RSS 81 -> 35.6MB).
- **Jitter pads follow the object's semantics** (were always nursery-bound; a diverted
  pad leaves the pretenure stream unjittered).

## 3. Instrumentation-only changes (not policy)

These change what is *observable*, not what the collector does. The first three predate
the 08-08 campaign window and sit on `shape/profiling`.

| date | change | where · sha | note |
|---|---|---|---|
| 08-06 | `MMTK_PAUSE_LOG=<path>` — per-pause NDJSON records | `binding/src/collection.rs`, `include/mmtk_ocaml.h`, `runtime/mmtk.c` · `a9f7b2a0b` | records buffered in memory (a parked mutator must not do I/O); 24 B/record; off by default, one relaxed atomic load per pause when disarmed |
| 08-06 | GC worker threads named `mmtk-gc-worker` | `binding/src/collection.rs` · `0723e544a` | 14 bytes (Linux truncates `comm` at 15); makes per-TID `/proc` GC/mutator attribution possible without root, and is what the hybrid classifier keys on |
| 08-07 | `MMTK_MUTATOR_GC_TIME=1` — TSC accounting of mutator-side GC entry points | `runtime/mmtk.c` · `6851ccfd4` | wraps the region barrier, SATB barrier, TLAB refill and the `alloc_shr` pair; per-domain `u64`; **subtracts parked time**, else one blocking refill books a whole pause as mutator CPU |
| 08-08 | jitter-filler counter — `[mmtk] jitter fillers: N` at exit | `runtime/mmtk.c` · `5a64cd691` | every run self-verifies that the knob actually fired (matmul-768: 2307 fillers ≈ one per matrix row). The same commit fixes a knob-declaration placement bug that broke the bytecode build — the env-arming block referenced the knob variables before their declarations, missed because `make -C runtime libasmrun.a` silently no-ops (root `make runtime/libasmrun.a` is the real target) |

Cross-validations: logged pauses sum to the independently accumulated total (GenImmix 259
pauses / 2280 ms vs `MMTK_VERBOSE`'s 2279 ms; Bactrian 233 / 1554 vs 1554), and
`MMTK_MUTATOR_GC_TIME`'s excluded parked time reads 1212.9 ms against `MMTK_VERBOSE`'s
1205 ms — 0.7% apart. Its first measurement was itself a result: mutator-side GC work on
binarytrees-20 is ~52 ms (barrier 0.035 ms), far too small to explain the ~0.9 s
mutator-CPU gap — establishing early that the gap is **not** misattributed GC work.

## 4. Dead ends tried and refuted

1. **LOS routing (`MMTK_LOS_THRESHOLD`, `c225f01d1`).** Route large-ish objects out of the
   nursery bump path into the LOS; 2056 bytes mimics stock's `Max_young_wosize` split.
   **Anti-productive** — matmul-768 (single-rep peek): ≥2056 B gives 9.57 G cycles /
   905.7 M LLC-loads and ≥4096 B gives 9.71 G / 905.9 M, against unmodified Bactrian's
   8.70 G / 739.3 M. Page-aligned placement has *zero* low-bit entropy: a perfectly regular
   8 KiB pitch, i.e. the disease itself. The ≥8192 B negative control (rows stay
   bump-allocated) reads 9.16 G / 686.1 M ≈ stock, as predicted. Routing verified live via
   RSS 23.7 → 73.5 MiB, so the refutation is of the technique, not of the plumbing. Knob
   retained; this experiment is what motivated jitter (§2a).
2. **Byte-scale jitter (v1, 8–128 B pads).** Fixed the pathological pitch (mm768 739 M →
   74 M) but *created* a new one at the benign size (mm800 140 M → 217 M). Entropy must be
   line-granular. Superseded by v2/v3. Likewise 7- and 8-bit entropy regress on matmul —
   6 bits is the measured knee.
3. **TLAB `prefetchw` on refill** — hurts everywhere; numbers and mechanism in §2c. Knob
   kept, default off.
4. **Nursery-shrink-for-warmth.** The store-frontier diagnosis suggests a small,
   L2-resident nursery. Measured on binarytrees-20 (heap 192, T=1), it is a catastrophe:

   | nursery | GCs | whole cyc | whole ins | wall | corrW |
   |---|---|---|---|---|---|
   | default (64 M scaled) | 57 | 13.1 G | 25.1 G | 3613 ms | 2.46 s |
   | 32 M | 115 | 19.0 G | 36.0 G | 4920 ms | 2.88 s |
   | 16 M | 229 | 29.1 G | 55.9 G | 7087 ms | 3.71 s |
   | 8 M | 458 | 45.6 G | 84.9 G | 10231 ms | 5.55 s |
   | 4 M | 924 | 78.6 G | 138.7 G | 16337 ms | 9.65 s |
   | 2 M | 1864 | 140.9 G | 239.6 G | 27428 ms | 17.98 s |

   Warmth never materialises. Causes separated: premature promotion fills the mature space
   with garbage (fulls 6 → 186 at 2 MiB) and park/wake futex traffic scales 56 → 20,511
   calls. kb is nursery-**insensitive** in W (corrW flat at ~1.39–1.61), so warmth is not
   kb's mechanism either. Partially rehabilitated by the pacer (§2d) — the 186 fulls were
   largely the backstop artefact, and LU/spectralnorm now run at `Fixed:4MiB`/`Fixed:8MiB`
   — but bt and kb still prefer the large nursery: their premature promotion is *real*
   survivors.
5. **Promotion-scatter hypothesis.** Round 2 proposed that MMTk's work-packet BFS tracing
   destroys the parent-child adjacency vanilla's first-child-first `oldify` preserves,
   making every tree hop an unprefetchable dependent load. **Refuted** in round 3b: the
   Bactrian mutator's loads hit L1 at 98.9% (`mem_load_retired` L1hit 3.69 G, L2hit
   0.04 G, L3hit ≈ 0) — pointer chasing is fine. The stalls are on the store side
   (`resource_stalls.sb`: LU 14.9% of cycles vs vanilla's 1.4%; spectralnorm 7.6% vs 0.1%;
   bt 4.4% vs 1.1%). Deprioritised behind the store-frontier work; no scan-order change was
   made.
6. **Core-migration / run-placement.** Never a separately-tested hypothesis — it was ruled
   out up front by round 1's technique-validation matrix: binarytrees ins_ratio holds at
   0.824–0.855 under the standard pin (0-13), single-core, unpinned, and a drift re-pass,
   with 0.15% rep variance. Only an SMT-sibling pair moves the cycle ratio (1.14 → 1.57),
   which is expected and is why `--cpu-set auto` derives one thread per physical core.

## 5. Next

- **Nursery aging (in progress).** Survive N minors before promotion, so a small, warm
  nursery becomes viable for survivor-heavy workloads — the remaining lever for
  binarytrees, whose W-cyc 1.239 leaves ~1.4 G excess cycles decomposing into store
  frontier (SB-full 0.45 G), post-GC warmth loss, and streaming L2/L3 latency at the
  64 MiB nursery. Bactrian-plan-local by construction; keep it out of LXR paths.
- **matmul residual — RESOLVED 2026-08-10** by Max_young_wosize pretenuring + the
  overflow-block phase rotation (section 2b): 1.03x vanilla at bare defaults,
  LLC-loads at the floor. The "different placement mechanism" was stock's own law.
- **Per-minor cost (LU, W-cyc 1.110).** Post-GC cache-warmth loss across 3282 minors. LU
  has zero survivors, which pins the marginal cost of an *empty* collection at ~113 µs —
  so the per-collection floor is copy-cost × survivors plus a small constant, not a large
  constant. Attacking that constant (packet overhead, park/futex churn, STW rendezvous)
  is the mmtk-core scheduling phase.
