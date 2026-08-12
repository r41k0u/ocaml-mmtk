# Changes made, and the issue each targeted

The design-delta ledger: every deliberate change to Bactrian (or its build)
during the shape campaign, the *measured problem* it targeted, and what it
did. Complementary to `ISSUES-FIXED.md` (defects); this file is the
doctrine audit — per the project rule, every difference from vanilla must be
either MMTk scaffolding or carry a measured justification. Reverted
experiments are listed too: a null result recorded is a difference avoided.

| # | Change (knob / commit theme) | Targeted issue | Effect (measured) | Status |
|---|---|---|---|---|
| 1 | Bump granule 32→512 KB (`MMTK_BUMP_BLOCK_KB`) | 32 KB tail-skip phase-locked medium-object cache placement (matmul LLC 213–903 M vs 57 M floor) | matmul at the LLC floor; 2–10 % mutator savings panel-wide from rarer refills | **Default** |
| 2 | Allocation jitter (`MMTK_ALLOC_JITTER`, 6 bits, line-granular) | Exact-pitch conflict misses on same-sized medium streams | Part of matmul's floor; superseded partially by #7 | **Default** |
| 3 | Allocation-byte full-GC backstop (was minor-count) | Full-GC storms at small nurseries (cadence denominated in minors, not allocation — stock's law) | Small nurseries viable; mark cadence 27–29/run matched | **Default** |
| 4 | UP-trace plain-op mode (`up_trace`) | 5.7 locked RMWs per traced object with a single tracer (vanilla: 0 — no one to race) | RMWs/object → 1.1; bt 0.90× | **Default** (auto-armed, T=1 STW only) |
| 5 | Max_young_wosize pretenuring (`MMTK_MEDIUM_NONMOVING`) | ≥2056 B blocks transited our nursery; stock births them mature — a *placement-law* difference | matmul nursery-independent 1.03–1.05×; removed a vanilla-delta | **Default (Bactrian)** |
| 6 | Same-stream jitter pads | Pads diverted to the nursery left the pretenure stream at exact pitch | Erased a +10 % matmul regression from #5 | **Default** |
| 7 | Overflow-block line-phase rotation (`MMTK_OVERFLOW_PHASE_LINES`) | Immix overflow cursor re-aligns every 32 KB → per-block cache-set phase reset (glibc arenas never re-align) | matmul 904/205 M LLC-loads → 58 M | **Default** |
| 8 | Remset immediate filter (`Is_block` gate) | Barrier logged non-pointer stores; stock's ref-table doesn't | matmul RSS 81→35.6 MB | **Default** (issue 3 in ISSUES-FIXED) |
| 9 | Thin LTO + codegen-units=1 | Binding slot/scanning layer outlined across the crate boundary (a constructor at 6 % of worker) | GC −13 % on the fixed workload | **Default build** |
| 10 | Header-sentinel forwarding (`HEADER_FORWARDING_SENTINEL`) | Side-table forwarding state: a side load per visit + 2 stores per copy (vanilla: discriminate on the header value — oldify's protocol) | GC −5 % more; zero side traffic in the forwarding path | **Default** (UP only) |
| 11 | UP direct-trace closure (nursery drain) | Every trace generation round-tripped packet alloc/schedule/dispatch (vanilla: a todo-list loop) | GC −6 % more (cumulative −23 %, ~260 cy/object); copy order = stock's parent-then-children | **Default** (UP only) |
| 12 | ~~Full-heap direct drains (layer + LIFO)~~ | Same target as #11 at full-GC scale | **Refuted ×2**: +8 % / +44 % — the packet system wins at full-heap scale | **Reverted** |
| 13 | Sliced-STW marking (`MMTK_MARK_SLICED`, 2 ms quanta) | 78–122 ms monolithic Full pauses (D3 tail vs vanilla's 15 ms); worker-concurrent alternative measured +7.9 G mutator cycles of LLC interference | Max pause 8.0 ms (below vanilla's 15.2); W −13 % vs STW-full mode; UP stays armed through cycles | **Default** |
| 14 | ~~LOS start-phase rotation~~ | spectralnorm's page-aligned LOS placement hypothesis | **Null result** (5.25 = 5.26 G); hypothesis refuted, reverted per doctrine | **Reverted** |
| 15 | JCC mitigation, all three code sources (`-mbranches-within-32B-boundaries`) | The layout lottery (ISSUES-FIXED 7): single-build W comparisons unsound at <15 % granularity | matmul 0.98×, kb 0.98×, fannkuch 1.00× (both sides); deterministic layouts | **Standing build config** |
| 16 | D2 period calibration (margin 120→14 %, `MMTK_MATURE_OVERHEAD_PCT`) | Cycle period 15 vs vanilla's 29 at stock-parity config (same law, different base semantics) | 28 vs 29 cycles — D2 matched | **Default** |
| 17 | Nursery default 64→16 MiB | 64 MiB frontier wraps outside LLC → DRAM-cold allocation stores (LU 1.23× outlier); 16 MiB is the balanced panel point | Panel consistency over bt surplus (bt 1.08, LU 1.14, sp 1.05, kb 1.09 pre-calibration; final numbers in the comprehensive report) | **Default** |
| 18 | Sliced-quanta budget (`MMTK_MARK_SLICE_MS=2`) | Quantum length ≈ a stock-parity minor pause, keeping mid-cycle pauses in vanilla's slice class | Cycle pauses mean 3.6 ms | **Default** |
| — | Worker-concurrent marking, adaptive-STW threshold, aging, madvise-on-release, frontier warmer | Earlier-campaign dials, all off/superseded by the above; kept as knobs for many-core / experiment use | documented in SHAPE rounds 1–22 | **Knobs** |

**Doctrine audit summary.** Changes 1–11, 13, 16–18 either *remove* a
vanilla-difference (3, 5, 8, 10, 11, 16 — each implements a stock law we
lacked) or are MMTk-side scaffolding standing in for what stock gets from
glibc/its arena for free (1, 2, 6, 7). Change 13 is the one deliberate
architectural liberty — quanta on a worker instead of the mutator — justified
by the D1-invariance argument (KC's framing) and measured to *dominate* both
alternatives. Change 15 is measurement methodology, applied to both sides.
Changes 12 and 14 are the doctrine working as intended: implemented, measured,
refuted, reverted, recorded.
