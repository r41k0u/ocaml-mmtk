# The five dimensions — what we measure and why

**The claim being defended:** `Bactrian` is the MMTk equivalent of stock OCaml 5.5's
garbage collector. Not "a faster GC" and not "a different GC that happens to be
close" — the same collector *architecture*, expressed in MMTk, with the same
space-time behaviour. Every dimension below is one axis of "the same behaviour",
measured against pristine OCaml 5.5.0 (`f5238509d`) on the same host, same
benchmarks, byte-identical program outputs.

Per KC's framing: vanilla marks and sweeps in slices *on the mutator*, Bactrian
uses dedicated GC workers — that mechanism difference is fine. What must match is
the **shape**: how much CPU goes to GC vs real work, when collections happen, how
long the program is ever stopped, and how much memory it holds while doing it.

---

## D1 — CPU budget (the headline)

**Question:** out of every CPU cycle the process burns, how many do useful work
(`W`, mutator) and how many are collection (`G`)?

**Why it matters:** it is the throughput story, and it is invariant to *where*
GC work runs (mutator slices vs dedicated workers) — which is exactly what makes
"dedicated workers are fine" a defensible claim rather than a concession.

**Metric:** whole-process cycles ratio vs vanilla, plus the W/G split
(worker threads counted by identity, mutator cycles classified by symbol).
Instruction counts are tracked alongside — instruction parity proves we do the
same *work*; any cycles gap is then stalls, not algorithm.

**Where we stand:** panel of 8 benches: binarytrees **0.84×** vanilla (below it);
nbody / fannkuch / mandelbrot / kb ≈ 1.0×; spectralnorm 1.07×; matmul and LU sit
on a *code-layout lottery* (proven by matched builds — see gaps), not on GC cost.
Instruction parity holds panel-wide.

## D2 — Pacing (when collections happen)

**Question:** does the collector run its cycles at the same rhythm vanilla does —
so many collections per gigabyte allocated?

**Why it matters:** two collectors with the same total cost but different rhythm
have different floating-garbage, different pause placement, different memory
curves. Matching pacing means matching the *law* that triggers collection, not
tuning until one number agrees.

**Metric:** cumulative GC events vs cumulative bytes allocated; count of minor
collections and major cycles; which trigger fired (mature-pressure vs
allocation-budget — we log the attribution).

**Where we stand:** minor cadence matches at the stock-parity 2 MiB nursery
(~2400 minors vs vanilla's ~3554 pause events on binarytrees). Major cycles: 15
vs vanilla's 29 — the trigger *law* is now structurally identical (pressure
percentage over post-cycle baseline + allocation budget measured from cycle
start); the remaining delta is one constant (our overhead % vs vanilla's
`space_overhead`) — a calibration decision, not a mechanism.

## D3 — Pauses / mutator utilization

**Question:** when the program is stopped, how long is it stopped — especially at
the tail?

**Why it matters:** latency. A collector can win D1 and still be unusable if it
stops the world for 100 ms at a time. Vanilla's signature is thousands of tiny
pauses (its incremental mark slices run *on* the mutator and count as pauses).

**Metric:** the full pause-duration distribution (count, mean, p95, max) from a
zero-overhead in-pause logger, cross-validated against vanilla's
`runtime_events`.

**Where we stand:** **matched, and slightly better than vanilla.** At the 2 MiB
nursery: max pause **8.0 ms vs vanilla's 15.2 ms** (before this campaign our max
was 122 ms). Achieved by sliced-STW marking — stock's mark-slice idea, executed
as bounded 2 ms quanta inside nursery pauses.

## D4 — Footprint over time

**Question:** how much memory does the process hold while running — the sawtooth
amplitude and the floor?

**Metric:** RSS sampled over wall time; peak RSS per bench.

**Where we stand:** the fixed benchmark heap (192 MiB pinned, chosen for
determinism) inflates our RSS on low-live benches (pages touched are never
returned); at memory parity the comparison is run with the dynamic
(`live × 2.2`) heap, mirroring stock's `space_overhead`. Known standing costs: a
~26 MiB startup floor (metadata mappings) and nursery residency. Medium-object
pretenuring removed the one pathological case (matmul remembered-set blow-up:
81 MB → 35 MB).

## D5 — Space-time frontier

**Question:** if you give both collectors the same memory budget, who is faster —
across the whole range of budgets?

**Metric:** throughput vs *measured* peak RSS, swept over heap sizes /
`space_overhead` settings. This is the honest single picture: any GC can win
time by wasting space.

**Where we stand:** mapped in the earlier campaign (fig9); the curves cross near
vanilla's operating point. Re-sweeping post-campaign is pending — the G-side
improvements since should shift our curve left.

---

*Instruments and their validation live in `gc/mmtk/SHAPE.md` (rounds 1–25 are the
full lab notebook). All comparisons: church (Xeon, pinned cores, ASLR off),
medians of 3+, byte-identical outputs enforced by a 16-cell golden gate.*
