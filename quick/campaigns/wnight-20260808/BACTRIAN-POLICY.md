# The Bactrian policy — what the collector actually does (2026-08-14)

The plan as it ships today (fork `1d265d3a6`), stage by stage, with
vanilla 5.5's behavior alongside at every step. Env knobs in parentheses.

## 1. Where an allocation goes (birth policy)

Every allocation is routed by size, mirroring vanilla's own routing:

| size | Bactrian puts it | vanilla puts it |
|---|---|---|
| < 2056 B (`Max_young_wosize` incl. header) | **nursery** (bump-pointer TLAB) | minor heap (bump) |
| 2056 B – 16 KB (the "medium band") | **mature Immix space directly** — never transits the nursery (`MMTK_MEDIUM_NONMOVING=1`, the pretenuring law from round 23) | major heap directly (`caml_alloc_shr` → size-class pools) |
| > 16 KB | **large-object space** (LOS, non-moving, page-granular) | major heap (large alloc) |

Native code allocates from a TLAB that is literally a slice of nursery
memory, so there is no special code generation — the same fast path as
vanilla's `young_ptr` bump. Medium-band births are unlogged at birth so
the generational write barrier will remember their pointers to young data.

## 2. The nursery and minor GC (the promotion policy)

- **Size**: bounded 2–16 MB by default, growing with allocation demand
  (`MMTK_NURSERY`; scaled per domain). Vanilla's minor heap is a fixed
  2 MB per domain. This is our biggest deliberate deviation and it is a
  throughput dial — see the nursery-size experiment report.
- **Trigger**: the nursery fills → stop-the-world minor collection. All
  domains stop (MMTk's single STW handshake).
- **What survives, and where it goes**: the minor GC traces from roots
  plus the remembered set. **Every survivor is promoted to the mature
  Immix space** — there is no aging, no "survive two minors first"
  (an aging mode exists behind `MMTK_NURSERY_AGE` but is off). This is
  exactly vanilla's policy: its `oldify` promotes every minor-heap
  survivor to the major heap at every minor GC.
- **How survivors are found — the remembered set**: mature objects that
  had a young pointer stored into them since the last minor. Vanilla
  remembers the exact *slots* (its ref table). We remember the *objects*
  (a per-object "unlog" bit; the first old→young store logs the object)
  and rescan all of a logged object's fields at the minor. Object-grain
  is cheaper per store but costlier per minor when a huge old object is
  hot (mature_mutation's 2 MB table — the one bench built to expose it).
- **The copy itself**: MMTk's generic trace, or the opt-in
  `MMTK_UP_OLDIFY=1` fast path — a binding-native loop shaped like
  vanilla's minor_gc.c (single tracer, world stopped, plain unsynchronized
  ops, forwarding via a sentinel written into the header word,
  layer-batched queue). Cost per promoted object: ~345–400 cycles vs
  vanilla's ~100 — the single biggest remaining D1 factor (attribution:
  ~160–190 cycles of it is MMTk-core machinery).

## 3. The mature pool (major heap)

An **Immix space**: memory in 32 KB blocks split into 256 B lines.
Promoted survivors and medium-band births bump-allocate into free lines
of partially-filled blocks (or fresh blocks). Reclamation is at **line
granularity** — a line is freed only when *no* live object touches it.

Vanilla's major heap is a **free-list mark-sweep**: same 32 KB pool
granularity, but reclamation is per-object — a dead object's cell is
relinked into a size-class free list and reused in place.

Consequences of that one difference:
- Immix wins locality (bump allocation packs related objects; matmul/LU
  live at ~parity because of it).
- Immix loses on interleaved small dead/live: a line with one live
  24-byte object keeps all 256 bytes (mature_mutation pinned 120 MB with
  6.6 MB live). The **compaction law** (round 30d) is the answer: the
  major trace tallies truly-live bytes; when post-sweep reserved exceeds
  live by `MMTK_COMPACT_OVERHEAD_PCT` (100%), the next major evacuates
  every block (headroom-bounded) and returns the freed pages to the OS —
  stock's `Gc.max_overhead` compaction analog. Fires only in the
  monolithic-Full regime, where the tally is exact; measured zero
  false-fires on bt/kb/sp.
- The medium band *can* be routed to a true free-list space
  (`MMTK_MEDIUM_TO=freelist`, sound as of round 31) but stays on Immix:
  MMTk's free-list allocator is ~3–4× slower per allocation than
  vanilla's pools (matmul 1.33→4.52 s in the A/B).

The **LOS** holds >16 KB objects, non-moving, marked via a treadmill;
young LOS objects are promoted in place at minors.

## 4. When a major happens (pacing)

The heap itself: dynamic by default — after each major, the heap target
is `live × 2.2` (clamped 32 MB–RAM), vanilla's `space_overhead` idea
(`MMTK_HEAP_SIZE_MB` pins it instead; campaigns pin 192 MB).

A major is requested when any of these fire (evaluated after every minor
and every ~2 MB of mature-direct allocation — the "tick", so band/LOS-
heavy programs with no minors still pace):
1. **Pressure**: mature has grown past `post-sweep-baseline × 2.5`
   (`MMTK_MATURE_OVERHEAD_PCT=150`), above an 8 MB-or-one-nursery floor.
2. **Heap clamp** (concurrent plans): mature reached 80% of the heap
   limit (`MMTK_CONC_TRIGGER_PCT`) — start the cycle *before* exhaustion.
3. **Allocation backstop**: ~512 MB allocated since the last major
   (keeps weak/finalizer reclamation on a bounded schedule).
4. **Compaction law** (§3), riding a monolithic Full.

Vanilla paces its incremental mark/sweep slices off allocated words vs
`space_overhead`; our laws land at a comparable cadence (D2: binarytrees'
cumulative-STW curve tracks vanilla's).

## 5. How a major actually runs (two regimes)

**Throughput regime (nursery > 4 MB — the default n16):** the major is a
single **stop-the-world Full**: mark the whole heap, sweep, all in one
pause. Rationale (measured, round 30b): at n16 the *minor* pauses are
already ~45 ms (16 MB of survivors × per-object copy cost), so slicing
the major's marking cannot produce smaller pauses than the minors — it
just costs ~9% more total GC time. `MMTK_SLICE_MAX_NURSERY_MB=4` is the
gate.

**Latency regime (nursery ≤ 4 MB, e.g. `@2M`, or tick-paced workloads):**
a **sliced concurrent-style cycle**, vanilla's own discipline:
- **InitialMark pause**: snapshot roots, arm the SATB barrier, zero
  mature mark state. Also a normal minor.
- **Between pauses**: mutators run; the SATB (snapshot-at-the-beginning)
  deletion barrier logs overwritten pointers so nothing reachable at the
  snapshot is missed; objects born mature during the window are
  allocate-black (born marked — live by definition this cycle).
- **Marking quanta**: each subsequent minor pause also runs a bounded
  slice of mature marking — budget sized by stock's law,
  `debt / (runway ÷ nursery)` so marking completes within the runway
  (`MMTK_MARK_RATE_MBPMS`); mature-direct allocation drives quanta too.
- **FinalMark pause**: drain the last marking, process weaks/ephemerons/
  finalizers (batched here — vanilla clears weaks incrementally), collect
  the nursery.
- **Incremental sweep**: the mature sweep is chopped into ~2 ms quanta
  across following pauses (`MMTK_SWEEP_SLICE_MS`) — RSS falls gradually,
  stock's sweep slices.
- Measured at bt@2M: max pause 13.4 ms vs vanilla's 14.9.

Emergencies (allocation genuinely failing) degrade to a monolithic Full;
a spurious-emergency detector (round 30b) keeps pacing triggers from
being misread as failures.

## 6. The write barrier (both halves)

- **Generational half** (always on): object-grain remembering via the
  unlog bit — first old→young store logs the object for minor rescans.
  Vanilla: slot-grain ref table. (§2 discusses the trade.)
- **SATB half** (armed only during marking windows): on pointer
  overwrite, the *old* value is logged so the snapshot stays complete.
  Vanilla's incremental marker has its own (Yuasa-style) deletion
  barrier — same family.

## 7. Weak refs, ephemerons, finalizers

Processed at cycle completion (FinalMark or Full) over complete marks.
Vanilla clears them incrementally during its marking. Semantics
identical, timing coarser — weak_memo measures the timing as stderr
metrics and shows checksum parity at ~1.00×.

## 8. The knobs that define "default Bactrian" today

`Bounded:2–16MB` nursery · pretenure ON (band→Immix) · UP-oldify OFF
(opt-in) · margin 150% · clamp 80% · floor 8 MB · sliced marking ON with
the ≤4 MB feasibility gate · incremental sweep 2 ms · compaction law
100% · dynamic heap live×2.2 (32 MB floor).
