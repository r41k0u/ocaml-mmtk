# Allocation and GC architecture — `mmtk-ocaml` vs stock OCaml 5.5

Two questions from the project lead, answered from the repositories only. Every claim
cites a file (`ocaml-mmtk/…` = the fork; `vanilla-5.5.0/…` = stock 5.5.0) or a
numbered round in `ocaml-mmtk/gc/mmtk/SHAPE.md`. *Numbering note*: SHAPE.md's W-night
section runs **rounds 1–19** (HEAD `a93f4a79d`); there is no round 20, and no round-4
heading — "Tiny-nursery mutator CPU: solved" sits in its place. Later material, which
supersedes SHAPE.md where they disagree, is in this directory's `REPORT.md`
(**Addenda 7–8**) and `NIGHTLOG-20260810.md`, plus `NOTES.md` 2026-08-09.

---

# Q1 — What difference does MMTk make to allocation?

## 1.1 The size bands, side by side

| band | stock OCaml 5.5 | fork (MMTk always-on) |
|---|---|---|
| `wosize ≤ 256` (`Max_young_wosize`, `config.h:194`) | per-domain **2 MiB minor arena**, inline downward bump (`memory.h:228–241`) | **MMTk TLAB**: inline downward bump over an MMTk-owned block (`mmtk.c:87–94`) |
| `wosize > 256` | `caml_alloc_shr` (`alloc.c:39–50`, `memory.c:453`) → major heap | `caml_alloc_shr` → `caml_mmtk_alloc_shr` (`memory.c:476`, `mmtk.c:630`) |
| major, `whsize ≤ 128` (`SIZECLASS_MAX`, `sizeclasses.h:4`) | **size-class pool** (`shared_heap.c:504–513`), 4096-word pools (`sizeclasses.h:2`) | — no equivalent; DEFAULT semantics (nursery CopySpace) |
| major, `whsize > 128` | **`malloc` per object** (`large_allocate`, `shared_heap.c:480–491`, call at `:515`) | DEFAULT semantics until 16 KiB |
| `≥ 16 KiB` | still `malloc` (same path) | **MMTk LOS**, `CAML_MMTK_LOS_THRESHOLD` (`mmtk.c:130`), routed by `caml_mmtk_semantics` (`mmtk.c:538–545`) |

The two stock thresholds differ: `Max_young_wosize` (256 words) decides minor-vs-major
at the call site; `SIZECLASS_MAX` (128 *whsize*) pool-vs-`malloc` inside the major heap.

## 1.2 The small-object path

**Stock.** Each STW-participating domain commits its own minor arena
(`domain.c:478–500`), default `Minor_heap_def` = 262144 words = **2 MiB**
(`config.h:203`). `Alloc_small` is fully inline: subtract `Whsize_wosize(wosize)` from
`young_ptr`, one interrupt check, one header store with colour 0 (`memory.h:233–238`).
On exhaustion `caml_alloc_small_dispatch` (`minor_gc.c:1020`) runs a **minor GC** —
the arena is emptied and re-bumped from the top.

**Fork.** The same inline sequence survives, but the region under it is an MMTk block.
`caml_mmtk_refill_tlab` (`mmtk.c:690–739`) takes `[start,end)` from the plan's Default
allocator and repoints `young_start / young_end / young_ptr`, setting `young_trigger =
young_start` so the fast path bumps the whole block before the next refill. Exhaustion
**does not run a minor GC** — `caml_alloc_small_dispatch` calls refill instead
(`minor_gc.c:262–281`, call at `:272`); a collection only happens if MMTk's block
acquisition polls one. The first refill is at domain init (`mmtk.c:442–487`), which
also gates the plan: native code needs a bump/Immix Default allocator or it fatals.

The **granule** replaces stock's arena size: `MMTK_BUMP_BLOCK_KB`
(`gc/mmtk-core/src/util/alloc/bumpallocator.rs:12–35`), **default 512 KB** where
upstream mmtk-core shipped 32 KB — so a domain re-bumps a 512 KB window against
stock's 2 MiB, while the *nursery* behind it is 2–64 MiB scaled by live domain count
(`ocaml-mmtk/CLAUDE.md`). Bytecode skips the TLAB entirely: `caml_mmtk_alloc_small`
(`mmtk.c:610–628`) allocates per object and hand-bumps `stat_minor_words`.

## 1.3 The medium path — the real divergence

**Stock** splits medium objects twice. Anything with `wosize > 256` goes straight to
`caml_shared_try_alloc` (`shared_heap.c:493`), which pools it if `whsize ≤ 128` and
otherwise `malloc`s it individually (`:504` vs `:515`). Because `wosize > 256` implies
`whsize > 257 > 128`, **every direct over-`Max_young_wosize` allocation is a
`malloc`** — never transiting the minor heap, never copied by any GC. Promotion uses
the same entry (`alloc_shared` → `caml_shared_try_alloc`, `minor_gc.c:150–158`), so
pools serve `whsize ≤ 128` from *any* caller (promotion dominates) and a survivor of
128–256 words also lands in `malloc`.

**Fork** has no such split. `caml_mmtk_alloc_shr` (`mmtk.c:630–656`) asks
`caml_mmtk_semantics` (`mmtk.c:538–545`), which returns `SEM_DEFAULT` for everything
below 16 KiB — **the same nursery CopySpace bump allocator the small path uses**. So
medium objects transit the nursery, are copied by minors, and are promoted. Two knobs
emulate stock's split, both **off by default**: `MMTK_MEDIUM_NONMOVING` (≥ 2056 B =
`Max_young_wosize` + header, to a swept free-list space; `mmtk.c:137–145`) and
`MMTK_TEST_MALLOC_MEDIUM` (a *measurement instrument*, never a default;
`mmtk.c:147–155`, `:638–645`). Because bump placement is pitch-regular, the fork also
inserts a pseudo-random dead `Abstract_tag` filler before ≥ 2 KB DEFAULT allocations
(`caml_mmtk_jitter_pad`, 6 bits of line entropy; `mmtk.c:156–162`, `:556–601`).

## 1.4 The large path

Stock has **no separate large space**: `large_allocate` is `malloc(sz +
LARGE_ALLOC_HEADER_SZ)` (`shared_heap.c:481`), threaded onto `local->swept_large` and
marked/swept in place. The fork routes ≥ 16 KiB to MMTk's **LOS** (`mmtk.c:130`, `:541`)
— page-granular, non-moving, mark-only (`BACTRIAN.md:32–39`); the threshold sits
deliberately below the smallest line/block of any collecting plan.

## 1.5 Allocation-time metadata — the cost is *inverted*, not added

| | stock | fork |
|---|---|---|
| header at alloc | minor: `Make_header_with_reserved(wosize,tag,**0**,reserved)` (`memory.h:237`); major: colour from `caml_allocation_status()` (`shared_heap.c:518–520`) | `(wosize << 10) \| tag`, colour bits left 0 — "MMTk uses side metadata" (`gc/mmtk/common/src/header.rs:1–17`) |
| per-object side metadata at alloc | none | **none** — no `post_alloc`, VO bit not enabled (`NOTES.md:6058`) |
| zero-fill at alloc | none on the minor path | **disabled universally** (`mmtk.c:307–333`); the comment costs it at ~20% of cycles on alloc-heavy code. Exception: MarkCompact must keep it |
| startup metadata | ~2 MiB empty-program RSS | ~26 MiB fixed floor — side-metadata tables mapped at init (`BACTRIAN.md:88–99`) |

So the allocation *point* is not where MMTk pays; the metadata tax lands at **GC
time**. Round 16's worker profile at a 16 MiB nursery: **three side-metadata ops per
promoted object** (unlog + object mark + line mark, 11.5%) plus forwarding/metadata
CAS pairs at 11.6% — ~650 cycles/object vs vanilla's ~300, because "vanilla's
domain-local minor uses ZERO atomics and ZERO side metadata; MMTk pays them for
parallel-tracer generality even at `MMTK_THREADS=1`".

## 1.6 Who calls `malloc`

Stock calls `malloc` per object for every major-heap block above `SIZECLASS_MAX`
(`shared_heap.c:481`). The fork **never calls `malloc` for an OCaml heap object** —
every object comes from an MMTk space. Round 19 measured it with `ltrace`: **914
`malloc`s ≥ 2 KB on matmul-300 under vanilla vs 0 under the fork** (the Rust side still
`malloc`s its own internal structures; the measurement is OCaml objects ≥ 2 KB).

**Do not read that as a performance explanation.** Round 19 is a *refutation*:
`MMTK_TEST_MALLOC_MEDIUM` gave the fork literal glibc placement for the medium band and
changed nothing (5.73–5.78 G cycles vs stock 5.82–5.88 G; vanilla 4.65–4.71 G).
`MMTK_PLAN=NoGC` reads 5.80 G and the residual is identical across
NoGC/Immix/GenImmix/Bactrian — **ambient to the fork runtime process**, not a GC, plan,
barrier, placement, alignment, frequency or layout effect. 914-vs-0 is a real
architectural difference with a *measured-null* performance consequence.

## 1.7 Measured consequences (SHAPE.md)

- **Store-frontier stalls (rounds 3b, 5–6).** Bactrian's bt mutator hits L1 on 98.9%
  of loads yet burns `cycle_activity.stalls_mem_any` = 1.42 G (18% of mutator cycles):
  bump stores into never-touched cold lines drain through the store buffer at RFO
  latency. `resource_stalls.sb`: LU 14.9% vs vanilla 1.4%, spectralnorm 7.6% vs 0.1%,
  bt 4.4% vs 1.1%. Vanilla's 2 MiB arena keeps the write frontier L2-resident; a
  64 MiB streaming nursery cannot. Prefetching the fresh block at refill was
  **refuted** (`MMTK_TLAB_PREFETCH`: LU 7.38 → 9.14 G). The dial is real — round 11:
  bt W-ratio 1.21 at the default nursery, **1.06** at an L3-resident `Fixed:16M`.
- **Placement regimes (rounds 1, 10, 13).** The *same binary* measured LLC-loads of
  213 M / 739 M / 903–1021 M depending on layout, against vanilla's 57 M floor from
  size-class pools. Round 1 established causality (jitter cut matmul-768's excess 10×,
  739 → 74 M) and refuted LOS routing (page alignment = zero low-bit entropy). Round
  13 closed it: the 32 KB granule's **tail-skip** phase-locked cache-set placement; at
  `MMTK_BUMP_BLOCK_KB=512` matmul lands exactly on vanilla's floor (57.1 M), and
  rarer refills pay every allocating bench 2–10% of mutator cycles. The two fixes are
  **not redundant** — Addendum 8's re-verification at HEAD: mm768 without jitter
  reads 115.5 M LLC-loads *even at granule 512*, vs 57.1 M with it.
- **All-medium-through-the-nursery (round 17).** A global `Fixed:16M` is impossible:
  matmul's live matrices (~19 MB) exceed the nursery, where vanilla pretenures
  > `Max_young_wosize` blocks straight to the major heap — measured 41.4 G (8.9×).
  **Superseded in part**: `NOTES.md` 2026-08-09 root-caused that catastrophe to the
  poll-trap livelock (emitted polls trap on `young_ptr <= young_limit`, every C-side
  check tests strict `<`; ~453 M round-trips, 82 G mutator instructions). Fixed in
  `domain.c`; mm@16M fell 3.66 s → 0.95 s (default 0.83 s) and 57 G → 8.3 G
  (Addendum 7). Post-fix (`NIGHTLOG-20260810.md` item A4) a 16 MiB nursery now
  dominates **both W and RSS on 4 of 5 benches** (bt 6.72 → 5.90 G W, 207 → 173 MB;
  LU 6.18 → 5.63 G, 93 → 44 MB); the sole blocker class is allocation bursts larger
  than the nursery — matmul, where every medium object transits it. So the medium
  band is what gates a small-nursery default; matmul is no longer the argument for it.
- **Panel as certified:** W-cycle ratios (round 13, pt-attach) kb 0.98, bt @
  `Fixed:16M` **1.009**, spectralnorm 1.05, matmul-768 1.15, bt default 1.16, LU 1.16.
  Addendum 8 settles the companion question: **work-instruction ratios are 0.963–1.007
  panel-wide** (bt *fewer*) — every W-cycle excess is IPC/stalls, never extra work.

---

# Q2 — Bactrian vs the vanilla collector

## 2.1 Axis by axis (condensed from `BACTRIAN.md:13–23`, the authoritative table)

| axis | vanilla OCaml 5.5 | Bactrian | matched? |
|---|---|---|---|
| young generation | per-domain 2 MiB minor arenas, copying, emptied wholesale at an STW rendezvous | shared **CopySpace** nursery handed out as per-domain TLABs, emptied wholesale at an STW pause | yes (shape) |
| promotion | Cheney copy inline on the mutator (`oldify_one`, `minor_gc.c:241`; `oldify_mopup`, `:410`); survivors promote at **age 0** into the non-moving pooled major (`alloc_shared`, `:150–158`) | MMTk STW handshake + work packets on GC workers; survivors promote at age 0 into Immix (`MMTK_NURSERY_AGE` exists but is default-off and measured negative for bt — round 9) | no — ~4× per-minor floor |
| mature space | non-moving, **size-class pools** + per-object `malloc` | **Immix** lines/blocks; STW defrag only at `Full` | ~analogous |
| major mark | incremental **slices on the mutator domains**, paced by allocated words (`major_gc.c:875–983`) | **concurrent on dedicated GC workers** racing the mutators, with adaptive STW below a threshold | no — same "mostly concurrent", different executor |
| sweep | incremental/lazy, each domain sweeps its own pools in slices (`Phase_sweep_main`, `major_gc.c:142–148`; `pool_sweep`, `shared_heap.c:537`) | **STW inside FinalMark** (Immix sweep packets in the pause) | **no — the biggest divergence** |
| pacing | allocated words vs `space_overhead` | mature pressure (+120%) or an **allocation-byte** backstop | no — pressure-driven |

## 2.2 The two cycles

```
vanilla:  [STW flip] -> mark slices ON THE MUTATORS (allocation-paced)
          ... STW minors interleave ...   [STW flip] -> sweep slices ON THE MUTATORS
Bactrian: [InitialMark = minor GC + snapshot seeding]
          -> GC WORKERS mark concurrently (minors interleave; SATB catches deletions)
          -> [FinalMark = minor GC + remark + weak/finalisers + STW MATURE SWEEP]
```
(`BACTRIAN.md:56–71`.) Every Bactrian transition rides a minor collection — which is
also what makes it sound for the concurrent marker to skip young objects entirely.

**Adaptive marking (round 8, `NOTES.md` 2026-08-08 "later").** A concurrent marker
streaming a *small* live set through the shared LLC costs more in mutator stalls and
SATB traffic than it saves in pause time, so a major cycle now runs as a plain STW
`Pause::Full` when the Immix reserved size is below
**`MMTK_CONC_MARK_MIN_MATURE_MB` (default 256; 0 restores always-concurrent)** —
`gc/mmtk-core/src/plan/concurrent/bactrian/global.rs:687,806`, strictly plan-local.
bt-20: mutator 7.84 → 6.78 G cycles, 14.17 → 13.40 G instructions, W-cyc 1.355 → 1.239.

## 2.3 Barriers

Both have **no read barrier** and no barrier on initializing writes
(`BACTRIAN.md:41–54`). Bactrian arms *two* halves at once (`mmtk.c:295–305`):

- **SATB deletion barrier**, marking-gated, slot-granular, no dedup bit, young-value
  filtered — deliberately "literally stock's `caml_darken(old)` shape" rather than
  ConcurrentImmix's per-object unlog-bit protocol, which would collide with the
  generational half's ownership of that bit.
- **Generational object-remembering barrier** for mature→young edges, coarser than
  stock's: stock records a slot only when the *stored value* is young, the fork's
  region barrier records every mutated mature slot regardless. A value-filtered
  remset is a known cheap improvement (`BACTRIAN.md:126–127`) — though round 7's "kb
  correction" withdraws the remset as kb's specific culprit (no remset symbol ranks).

## 2.4 Pacing — the full-GC backstop

Vanilla budgets major work by **allocated words**: `alloc_counter` (`major_gc.c:755`,
advanced at `:983`) and the slice formula `PH = allocated_words / G` against
`caml_percent_free` (`major_gc.c:895–925`), so a major cycle always progresses under
allocation whatever the headroom. Bactrian collects on **memory pressure** — at a big
pinned heap a program can legitimately finish with zero collections
(`BACTRIAN.md:78–86`). The backstop that keeps `Gc.major_collections` advancing is
`collection.rs:556–623`; its denomination changed during W-night:

| trigger | rule | source |
|---|---|---|
| mature pressure | mature reserved > baseline × (1 + 120%) **and** > floor `max(32 MiB, nursery)` | `collection.rs:161–164`, `:247–265`, `:605–610` |
| cadence backstop (default) | **allocated bytes** ≥ 8 × 64 MiB × ndomains | `collection.rs:203–222`, `:614–618` |
| cadence backstop (override) | `MMTK_FULL_GC_CADENCE` = a minor count, 8 × ndomains | `collection.rs:225–245` |

The old minor-denominated law scaled **inversely** with nursery size: at `Fixed:2MiB`
it forced a whole-heap collection every ~16 MiB allocated — 186 fulls on bt-20 where
the default does 6, a manufactured full-GC storm (141 G cycles vs 46 G with it
suppressed; `NOTES.md` 2026-08-08, `collection.rs:203–212`). The whole block is gated
on `plan.generational()`, so LXR is inert here.

## 2.5 Knobs

| knob | default | effect | source |
|---|---|---|---|
| `MMTK_PLAN` | `GenImmix` | `Bactrian` = the stock-architecture plan | `mmtk.c:275–276`; `CLAUDE.md` |
| `MMTK_NURSERY` | bounded 2–64 MiB × live domains | raw **bytes** only (`Fixed:8388608`); suffix form silently falls back | `CLAUDE.md` (ROADMAP #21 BUG B) |
| `MMTK_HEAP_SIZE_MB` | dynamic, `live × 2.2` after each full | pin for reproducibility — D2 is not reproducible unpinned (SHAPE "Protocol") | `mmtk.c:283–290` |
| `MMTK_THREADS` | `nproc` | worker count; policy from round 5–6: domains + workers ≤ physical cores | `CLAUDE.md` |
| `MMTK_BUMP_BLOCK_KB` | **512** (upstream 32) | bump granule; reaches vanilla's LLC floor on matmul | `bumpallocator.rs:12–35` |
| `MMTK_LOS_THRESHOLD` / `MMTK_ALLOC_JITTER` | 16384 B / **6** bits | large-object routing; de-regularizing the ≥ 2 KB bump pitch | `mmtk.c:130`, `:156–162` |
| `MMTK_CONC_MARK_MIN_MATURE_MB` | 256 | below this, mark STW instead of concurrently | `bactrian/global.rs:806` |
| `MMTK_FULL_GC_CADENCE` / `MMTK_NURSERY_AGE` | unset (bytes law) / 0 | revert the backstop to a minor count; survivor aging (correct but negative for bt, two known holes) | `collection.rs:236–243`; `NOTES.md` 2026-08-08 (night) |
| `MMTK_TLAB_PREFETCH`, `MMTK_FRONTIER_WARMER`, `MMTK_MEDIUM_NONMOVING`, `MMTK_TEST_MALLOC_MEDIUM` | off | measured-negative or instrument-only | `mmtk.c:137–172`, `:490–523` |
| `BACTRIAN_TRACE`, `BACTRIAN_NO_CONCURRENT` | off | pause counters; degrade cycles to STW `Full` | `BACTRIAN.md:129–134` |

## 2.6 Consequences for the shape dimensions

| architectural difference | dimension | measured effect |
|---|---|---|
| dedicated GC workers vs mark slices on the mutator | **D1** | `CPU/wall` 1.37 for Bactrian vs ~1.00 for vanilla and GenImmix — marking genuinely overlaps ("Early observations"). Flat symbol classification undercounts G (0.25 vs 0.42) because copying runs through libc `memmove`; the reconciled instrument is hybrid attribution (perf section) |
| fewer, larger collections (57 vs ~1800) | **D1** | Bactrian's collector executes *fewer* instructions than vanilla's (9.4 G vs ~15.7 G est., round 2); after adaptive marking + trace-path slim its GC **fraction is below vanilla's** on bt — 0.401 vs 0.501 at whole-process parity (`REPORT.md` Addendum 7) |
| 64 MiB streaming nursery vs 2 MiB L2-resident arena; bump placement vs size-class pools | **D1 (W side)** | the store-frontier residual (rounds 3b/5–6): round 10 shows bt mutator cycles *invariant* to worker cache domain, GC count and nursery size — purely cold-frontier stores. Placement closed by round 13's granule fix; round 19 rules the matmul remainder fork-ambient, not placement |
| pressure/allocation-byte pacing vs allocated-words slices | **D2** | the shipped default runs **58 collections against vanilla's ~1839** — 32× fewer. Stock-parity pacing is pure configuration (`Fixed:2097152` + `MMTK_FULL_GC_CADENCE` → 1867 vs 1839) but costs 5.4–7.7× wall, because the per-minor floor is ~7.5 ms against vanilla's 0.63 ms. **D2 matching is blocked on the per-collection floor, not on trigger design** (church 2026-08-07) |
| few large STW pauses (rendezvous + FinalMark sweep) vs many tiny incremental ones | **D3** | **Addendum 8 splits the verdict.** *Aggregate* STW favours Bactrian — bt: 57 pauses / **739 ms** (conc-mark) or 1468 ms (STW-mark) against vanilla's 3554 / 1970 ms. The *tail* is vanilla's, untouchably: p99 3.6 ms and max 15.2 ms vs our 98–225 ms fulls. (kb inverts on totals: vanilla 1885 / 195 ms vs 28 / 222 ms.) Reporting one summed number could support either claim — hence MMU/CDF curves |
| concurrent vs adaptive-STW marking | **D3 ↔ D1 dial** | conc-mark **halves both the tail and total STW** (1468 → 739 ms, p99 225 → 98) for +0.45 G mutator cycles (Addendum 8) — the explicit price of pause relief. Earlier framing stands: the worst pauses are nursery/full collections, not marking |
| mid-cycle floating garbage held to FinalMark; side-metadata tables | **D4** | ~26 MiB program-independent startup floor vs vanilla's ~2 MiB (`BACTRIAN.md:88–99`); measured timelines (Addendum 8, fig8): Bactrian-def **+40–90% RSS** on bt/kb/lu, most of which `Fixed:16M` closes (bt 173 vs 144 MB peak). Under multi-domain anti-scaling cycles stretch and it compounds — par_binarytrees d=8 at ~1.7 GB |
| space-for-time headroom (`live × 2.2`) + fixed copy reserve | **D5** | Addendum 8's bt frontier (fig9): Bactrian owns the **fast** end (3.34 s vs vanilla 3.62 s) at ~180 MB vs 144 MB; vanilla owns the **small** end (71 MB @ 5.9 s against our 159 MB @ 5.3 s floor). **Crossover ≈ 150–180 MB.** Round 12's sticky-nm proof (bt at 79% of vanilla's cycles, RSS ~172 vs ~140 MB) is the same trade seen from the plan side |
| worker pool vs inline slices, under domain scaling | **M1** | MMTk beats vanilla on wall *and* CPU at d=2–4 (d=4: 1.90–1.98 s vs 2.08 s); collapses at d=8 (15–17 CPU s vs 7.1) purely from oversubscription (church 2026-08-07). Policy fix, T=4–6 optimal at d=8 (rounds 5–6) |
