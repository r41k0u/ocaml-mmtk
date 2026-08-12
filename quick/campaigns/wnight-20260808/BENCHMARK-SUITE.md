# The benchmark suite — what each program tests, what's redundant, what's missing

Requested 2026-08-12. Characterizes the 8-bench quick panel as *GC shape
instruments*: each bench's memory behaviour, what it uniquely stresses, which
dimensions it can meaningfully measure, and an honest assessment of gaps.
Numbers from the wcomp battery (n16 default, calibrated pacing; minor words
are vanilla's odometer — equal on both sides by D2 validation).

## Why D2/D3 streamed only bt/kb (and D4 only bt/kb/LU) — the honest answer

The stream instruments were stood up during rounds 1–5 on the two benches
whose *shape* was known to diverge (bt, kb), and coverage stayed pragmatic.
Three benches (nbody, fannkuch, mandelbrot) genuinely produce empty streams —
zero-to-one GC events in entire runs — but **LU (205 GCs) and spectralnorm
(101 GCs) have real GC activity and should be streamed**; matmul at the
current defaults runs 0–1 GCs (its allocation is one pretenured init burst)
and produces a trivial stream. Action taken: the standing battery definition
now includes LU + sp in D2/D3/D4.

## Per-bench characterization

| bench | alloc volume (minor words) | live set | dominant size band | GCs (n16) | what it uniquely tests |
|---|--:|--:|---|--:|---|
| **binarytrees-20** | 458 M (≈3.7 GB) | ~30–100 MB phased | small blocks (3-word nodes) | 335 minors / 10 fulls | THE generational stress: allocation rate at survival; promotion economics; mature growth + cycle cadence; deep pointer-chase tracing. The only bench where the *whole* GC pipeline is hot. |
| **kb-50** (Knuth–Bendix) | 231 M (≈1.8 GB) | ~5–7 MB | small closures/terms | 120 minors / 3 fulls | Symbolic churn: short-lived small objects with a *stable* live set — minor-GC economics isolated from mature growth. Effect-handler/closure scanning. The bench that catches per-minor floor costs (and caught the infix-pointer bug). |
| **spectralnorm-3000** | small | ~1 MB + vectors | **LOS band** (24 KB vectors) | 101 GCs / 11 fulls | The only LOS-path bench: large-object allocation churn, page-granular placement, LOS frontier warmth. |
| **matmul-768** | one burst | ~14 MB matrices | **medium band** (6 KB rows, Max_young_wosize territory) | 0–1 | Medium-object placement law (pretenuring), cache-pitch sensitivity of same-sized streams. Allocation-*burst* behaviour (all rows at init) — the bench that exposed placement lotteries and the poll-trap livelock. |
| **LU-900** | continuous | ~6.5 MB | medium band (7 KB rows) + temporaries | 205 minors / 22 fulls | Continuous medium allocation + RMW store patterns — the allocation-frontier-warmth probe (store-side RFO). Complements matmul (burst) with steady-state medium churn. |
| **nbody-20M** | ~0 | ~KB | unboxed floats | 0 | Control: FP-pipeline mutator parity with GC idle. |
| **fannkuchredux-11** | ~0 | ~KB | int arrays | 0 | Control: int-array/branch mutator parity. (Caught the JCC layout lottery — the controls are also layout canaries, each with a different code shape.) |
| **mandelbrot-4000** | ~0 | ~KB | bit output | 0 | Control: branch+bit loop parity. |

**Dimension coverage by bench**: D1 — all 8. D2/D3 — bt, kb (rich), LU, sp
(moderate; now added), matmul (trivial), controls (empty). D4/D5 — bt, kb,
LU, sp meaningful; controls flat.

## Are any tests irrelevant?

**As GC-shape instruments, the three controls are mutually redundant** —
nbody, fannkuch, and mandelbrot all measure the same thing (mutator parity
with the GC idle). But I recommend keeping all three, for a reason this
campaign proved empirically: they are *layout canaries with three different
code shapes* (FP pipeline / int-array shuffle / branch loop), and fannkuch —
not the GC benches — was what exposed that vanilla's own build had a JCC
defect. They cost ~2 s each and de-risk the methodology. If one must go,
mandelbrot is the most redundant (its branch-loop profile overlaps fannkuch's
more than nbody's FP profile overlaps either).

**matmul post-pretenuring is half a control** (0–1 GCs at defaults) — but it
remains the *placement-law* regression test for the medium band and the
burst-allocation probe. Keep.

No bench is truly irrelevant; the suite's real problem is the opposite —
**coverage gaps**.

## What the suite does NOT test (gaps, ranked by how much they'd change the report)

1. **Mature mutation / remembered-set stress.** No bench mutates a large old
   heap (bt's trees are immutable once built; kb's live set is small). A
   graph-mutation or LRU-cache workload would exercise the write barrier and
   remset at volume — the one GC subsystem our D1 panel barely weights.
   Vanilla-vs-Bactrian barrier cost differences are currently *unmeasured*.
2. **Weak refs / ephemerons / finalizers.** Nothing in the panel touches
   them, yet our clear-timing (at fulls) differs structurally from vanilla's
   (incremental) — a real shape difference with **zero current coverage**.
   A weak-memo-table bench would expose it.
3. **Request-loop latency pattern.** All 8 are batch programs; D3/MMU is
   most meaningful for allocate-burst/settle/repeat workloads (servers).
   A synthetic request loop would make the D3 story externally credible.
4. **Fragmentation driver.** Nothing deliberately interleaves mixed-size
   allocate/free to stress mature utilization — the D5-critical behaviour;
   kb only brushes it. A fragmentation bench would probe defrag policy
   directly.
5. **String/bytes processing.** No byte-array churn (I/O-shaped workloads);
   OCaml practice is full of it.
6. **Macro programs.** The suite is CLBG micro. Sandmark-class macros
   (menhir, alt-ergo, irmin-style) or the compiler self-build would carry
   far more weight in a paper than any micro. (The self-build already runs
   in CI as a correctness gate — promoting it to a measured shape bench is
   nearly free.)
7. **Multi-domain shape.** par_* benches exist in the suite but the shape
   campaign has been single-domain by design; the D1–D5 story at d>1 is
   untouched (and worker-concurrent marking becomes live there).

## Recommendation

Keep all 8 (cheap, each earns its place); add, in order of report impact:
(a) a mature-mutation bench, (b) a weak/ephemeron bench, (c) the compiler
self-build as a macro shape bench, (d) a request-loop latency bench. (a) and
(b) directly cover the two GC subsystems the current panel cannot see; (c)
converts the paper's weakest point (micro-only) into its strongest.
