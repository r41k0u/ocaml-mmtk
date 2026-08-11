# Bactrian: every change, its cause, and its effect

Plain-language change log for the W-parity → shape-matching campaign
(2026-08-06 → 2026-08-11). Each entry: what was wrong, what we changed, what it
measurably did. Ordered chronologically. Benchmark shorthand: bt = binarytrees-20,
mm = matmul-768, ratios are cycles vs vanilla 5.5.0 on the same host.

---

## Phase A — finding and removing hidden mutator taxes

**1. The poll-trap livelock ("the 8.9× catastrophe").**
*Cause:* compiler-emitted poll points trap on `young_ptr <= young_limit`, but
every C-side check tested strict `<`. After a GC left the TLAB in an equality
state, an allocation-free compute phase re-trapped on *every poll*, doing nothing
each time — matmul ran 82 G instructions of pure poll-trap spin.
*Change:* the poll-path refill now uses the same `<=` the generated code traps on.
*Effect:* matmul@16M 3.66 s → 0.95 s. Every small-nursery config stopped
exploding.

**2. Bump-allocation granule 32 KB → 512 KB (`MMTK_BUMP_BLOCK_KB`).**
*Cause:* medium objects bump-allocated at size pitch got phase-locked into the
same cache sets every 32 KB block — matmul's LLC loads swung 213–903 M
run-to-run against vanilla's 57 M floor.
*Change:* larger TLAB acquisition granule (+ line-granular allocation jitter,
`MMTK_ALLOC_JITTER`, to break exact pitch).
*Effect:* matmul reached the 57 M LLC floor; every allocating bench saved 2–10 %
mutator cycles from rarer refills.

**3. Full-GC cadence re-denominated to allocation bytes.**
*Cause:* the old "every N minors" backstop made full-GC frequency depend on
nursery size — small nurseries triggered full-GC storms.
*Change:* the backstop counts allocated bytes (stock's law).
*Effect:* small nurseries became viable; mark-cycle cadence matched vanilla
(27–29 per run on bt).

## Phase B — making collection itself cost what vanilla's costs

**4. UP-trace: single-tracer plain-op mode.**
*Cause:* with one GC worker inside a stopped world there is nobody to race, yet
every traced object paid full atomics — 5.7 locked RMW instructions per object
(vanilla's oldify: zero; its mark state lives in the header).
*Change:* when worker count is 1 and the world is stopped, the trace uses plain
loads/stores (forwarding claim skipped, SeqCst → relaxed, metadata ops take
non-atomic twins). Armed per pause; multi-worker runs unchanged.
*Effect:* locked RMWs/object 5.7 → 1.1; bt whole-process reached **0.90×
vanilla**; identical outputs under every gate.

**5. Medium-object pretenuring (`Max_young_wosize` law) — default ON.**
*Cause:* stock never lets a block over `Max_young_wosize` transit the minor
heap (it goes straight to the major heap). We sent everything under 16 KB
through the nursery — matmul's 6 KB rows churned it (1.25–1.89× swinging with
nursery size, an alignment lottery between builds).
*Change:* ≥ 2056 B blocks are born in the mature Immix space (unlogged at
birth, live during marking windows). Three supporting fixes were required:
jitter pads must follow the object into the same allocation stream; fresh Immix
"overflow" blocks get a rotating cache-line start phase (glibc's contiguous
arena gives vanilla this for free); and initialising stores of immediates no
longer enter the remembered set (stock's own filter — without it matmul
retained 46 MB of remembered-set buffers).
*Effect:* matmul **1.03–1.05× vanilla and nursery-independent**; RSS 81 → 35 MB;
bt/kb/LU untouched.

**6. Link-time optimization (thin LTO) for the GC static library.**
*Cause:* the binding's per-slot scanning helpers live in a different crate from
the core trace loops; without LTO a trivial constructor was 6 % of worker
cycles.
*Change:* thin LTO + one codegen unit.
*Effect:* GC time on the fixed bt workload −13 %. Side discovery: the *mutator*
side of matmul/kb moved ±5–12 % purely from code re-layout with every counter
flat — the "fork-ambient" mystery is a **code-placement lottery**, now
reproducible on demand (fat vs thin LTO is a perfect matched pair).

**7. Header-sentinel forwarding — vanilla's oldify protocol, verbatim.**
*Cause:* forwarding state sat in a side table: one side-load per visited object,
a CAS + store per copy. Vanilla overwrites the header with the forwarding
pointer and discriminates on the value.
*Change:* under UP-trace, "forwarded" ⇔ the header word is numerically ≥ the
heap's start address (every real header is far below it). No side traffic at
all. The binding's infix-pointer disambiguator had silently depended on those
side bits — a forwarding pointer whose low byte spelled `Infix_tag` segfaulted
kb until that check became value-range too (it is now also cheaper and correct
in every mode).
*Effect:* GC time another −5 %; bt whole-process **0.85×**.

**8. Direct-trace closure for nursery pauses.**
*Cause:* each generation of the trace bounced through packet allocation, bucket
scheduling and a fresh work-packet object — scheduling machinery per object
generation, where vanilla's oldify walks a todo list.
*Change:* under UP-trace the whole nursery closure runs inside one packet with
an explicit work list (identical per-object protocol; copy order becomes
parent-then-children, stock's order).
*Effect:* GC time another −6 %: cumulative bt@16M GC **3100 → 2382 ms (−23 %)**;
bt whole-process **0.84×**. Two attempts to extend this to full-heap traces
measured *worse* than the packet system (a full-heap BFS frontier is millions of
objects; MMTk's 4096-object packets are the right structure there) — both
reverted, negative results recorded.

## Phase C — matching the pause shape

**9. Sliced-STW marking — default ON (`MMTK_MARK_SLICED=0` reverts).**
*Cause:* major-cycle marking ran as one monolithic stop-the-world Full pause:
78–122 ms, against vanilla's 15 ms worst pause. The obvious alternative —
marking concurrently on the worker while the mutator runs — we measured and
rejected: the marker streams the live set through the shared L3 *while the
mutator computes*, costing +7.9 G mutator cycles on bt (49 % whole-process).
Vanilla avoids that by serializing its mark slices with mutation; so do we.
*Change:* marking work parks in a plan-owned queue and executes as bounded
~2 ms quanta inside ordinary nursery pauses (one slice per minor — automatically
allocation-paced, like stock), FinalMark drains the remainder. UP-trace stays
armed through the whole cycle (one worker, world stopped ⇒ still a single
tracer), so phase-B economics apply to marking too.
*Effect:* max pause **122 → 8.0 ms — below vanilla's 15.2 ms**; and whole-process
*improved* 13 % over the STW-full mode. Two pacing bugs found and fixed en
route: a scheduler race fired a spurious zero-allocation "emergency" Full after
every cycle, and cycle completion never reset the pacing counters (the law now:
completion resets the pressure baseline, cycle start resets the allocation
budget — a monolithic Full is both at once, so that mode is bit-identical).

**10. LOS start-phase rotation (in flight, measuring now).**
*Cause:* spectralnorm (+7 %) refuted every data-side hypothesis (faults, TLB,
L1/LLC conflicts, 4K aliasing) except a top-down memory-bound rise (0.6 → 4.8 %)
— suspect: large objects are page-aligned, so same-shaped vectors sit at fully
correlated offsets; malloc'd large objects (stock's placement) never do.
*Change:* successive large objects start a rotating number of cache lines into
their first page.
*Effect:* being measured.

---

## Where the panel stands (church, medians, vs vanilla 5.5.0)

| bench | cycles | note |
|---|---|---|
| binarytrees | **0.84×** | below vanilla (UP-trace + oldify protocol + closure) |
| nbody, fannkuch, mandelbrot | 0.97–1.03× | parity |
| kb | 1.05× | parity-class; moved with code layout |
| spectralnorm | 1.07× | memory-bound residual, change 10 in flight |
| matmul | 1.03–1.17× | *layout lottery band* — 1.03 on a good draw |
| LU | 1.24–1.27× | layout lottery / fork-ambient (GC exonerated: reproduces under NoGC) |

Pauses: max 8.0 ms vs vanilla 15.2 (bt@2M). Mark cycles: 15 vs 29 (law matched,
constant pending calibration). Instruction parity panel-wide.

## Gaps still open

1. **D2 period calibration** — 15 vs 29 cycles/run: same trigger law, different
   operating constant (our pressure % vs vanilla's `space_overhead`). One-line
   calibration; decision pending (more cycles = more G, shifts D5).
2. **Per-minor economics** — total STW 4.1 s vs vanilla 2.0 s is *entirely* mean
   minor cost (1.66 vs 0.55 ms): ~260 cycles per promoted object vs vanilla's
   ~80. The remaining ~180 is the intrinsic scan/dispatch/copy layer of a
   VM-neutral framework; further folding trades away "Bactrian *is* MMTk".
3. **The layout lottery** (matmul, LU, kb, fannkuch ±5–12 %) — mutator cycles
   move with code placement, all PMU counters flat. We now have the control
   experiment (LTO matched pair); the fix direction is alignment hardening +
   reporting W across link draws. This is also a methodology point for the
   paper: single-build W comparisons at this granularity are not sound.
4. **spectralnorm memory-bound residual** — change 10 measuring.
5. **StickyImmix release-counter underflow** — pre-existing crash (not from this
   campaign; verified against the old tree), logged in NOTES, fix queued.
6. **Multi-domain scalability** — untouched by this campaign; the sliced-quanta
   design intentionally leaves worker-concurrent marking available as the
   many-core dial.
7. **Housekeeping** — mmtk-core commits currently travel by git bundle
   (no public fork of mmtk-core yet); D5 re-sweep post-campaign pending.
