# Replicating the ocaml-mmtk / Bactrian measurements

One command reproduces the presentation's data and charts on a fresh
Linux x86_64 machine:

```
git clone --branch shape/instruments https://github.com/r41k0u/ocaml-mmtk.git
bash ocaml-mmtk/quick/replicate/replicate.sh
```

What it does, in stages (each idempotent; rerun with `STAGES="run charts"`
etc. to redo parts):

1. **deps** — installs build tools, opam, rust; checks
   `kernel.perf_event_paranoid` (must be <= 2 for hardware cycle counts;
   otherwise the run degrades to wall-clock and says so).
2. **vanilla** — opam switch with stock OCaml 5.5.0 (+ `olly` for vanilla
   pause tails, if available).
3. **fork** — clones and builds ocaml-mmtk (OCaml 5.5 with MMTk as its only
   GC) into an installed prefix. ~15-30 min.
4. **bench** — builds the benchmark panel (9 CLBG/Sandmark programs + the two
   adversarial benchmarks in `quick/src/`) under both compilers.
5. **run** — the batteries. Byte-identical-output gate first, then:
   D1/D4 (3 reps cycles+instructions + peak RSS, both runtimes, memory-parity
   configs: Bactrian 192MB fixed + `MMTK_UP_OLDIFY=1` vs vanilla `o=500`);
   D2 (major-collection counts, Bactrian@2MB-nursery vs vanilla verbose);
   D3 (Bactrian pause streams via `MMTK_PAUSE_LOG`; vanilla via `olly`);
   D5 (vanilla `s`x`o` grid; Bactrian fixed-heap and nursery x overhead
   grids). Raw data lands in `$WORK/results`.
6. **charts** — regenerates the figures into `$WORK/charts`
   (`d1_ratios`, `d1_adversarial`, `d2_count`, `d3_curve`, `d4_rss`,
   `d5_scatter`).

Defaults: `WORK=$HOME/mmtk-replication`; runs pinned to NUMA node 0's
physical cores (`TASKSET=` to override). Expect different absolute numbers on
different hardware; the paper's operating point is a dual Xeon Gold 5120 with
runs pinned to one socket. Ratios and shapes are what should replicate.

Known caveats:
- The JCC-erratum alignment flag is applied to the fork build; the opam-built
  vanilla omits it, which can add up to ±5% layout noise on matmul-class
  benchmarks (the paper built both compilers with it).
- Vanilla per-pause streams (for the cumulative-STW overlay) need the `olly`
  tool; if it fails to install, that overlay renders Bactrian-only.
- The D5 Bactrian grid excludes cells where an explicit nursery >= half the
  dynamic-heap floor (a documented degenerate knob interaction).
