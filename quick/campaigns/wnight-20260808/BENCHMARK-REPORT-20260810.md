# Bactrian vs Vanilla — fresh benchmark report (2026-08-10, post UP-trace)

Operating point: church (2×Xeon Gold 5120), cores 0-13, performance governor,
`setarch -R`, heap 192 MiB vs vanilla `o=500`, `MMTK_THREADS=1`, outputs
byte-identical on every cell. Attribution: pt-attach (mutator vs worker
threads); W = mutator cycles. Build: `12e79cc0d` + mmtk-core `2ad2feecdd`.

## Headline

**binarytrees — the suite's only heavily-collecting benchmark — now runs at
10.30G whole-process cycles against vanilla's 11.5G: Bactrian is 10% faster
in total CPU** (3 reps ±0.01G), with a GC fraction of 0.35 vs vanilla's 0.50.

## What changed since the last report: UP-trace

When exactly one GC worker traces in a fully-stopped, non-marking world,
every synchronization primitive on the trace path is redundant. The binding
now proves those conditions per pause and mmtk-core takes plain-operation
twins: the forwarding claim-CAS is skipped outright, SeqCst stores (locked
XCHG on x86) become plain MOVs, and the side/header-metadata atomic
primitives take non-atomic paths. Fused marking pauses and multi-worker or
concurrent windows keep full atomics; LXR/RC paths never consult the flag.

Measured: **locked RMWs per copied object 5.7 → 1.1** (112.6M → 21.3M per
bt@16M run); worker G −22-25%; collection instructions −15%.

## Panel (defaults; W / G cycles, vanilla refs in parens)

| bench | W | G | whole | vanilla whole | ratio |
|-------|---|---|-------|---------------|-------|
| binarytrees | 6.55 (5.74) | 3.48 (5.76) | **10.30** | 11.5 | **0.90** |
| kb | 4.16* (3.95) | 0.52 (0.58) | 4.92 | 4.52 | 1.09 |
| LU | 6.30 (5.36) | 0.21 (~0) | 6.51 | 5.36 | 1.21† |
| spectralnorm | 5.02 (4.88) | 0.06 (~0) | 5.08 | 4.88 | 1.04 |
| matmul | 5.63 (4.64) | 0.00 (~0) | 5.63 | 4.64 | 1.21† |
| nbody/fannkuch/mandelbrot | — | ~0 both | — | — | 1.00/1.03/0.97 |

*kb W rep-band 3.85-4.16. †carries the characterized fork-ambient runtime
effect (plan-independent, NoGC-reproducible, all PMU counters at parity —
an open runtime item, not GC).

## The @16M nursery family (the W/RSS dial), post UP-trace

| bench | W @16M (ratio) | G @16M | RSS @16M |
|-------|---------------|--------|----------|
| binarytrees | **5.73 (0.99)** | 9.20 (was 12.3) | 173MB |
| kb | 4.14 | 1.21 (was 1.6) | 52MB |
| LU | 5.77 (1.08) | 0.29 | 44MB |
| spectralnorm | **4.65 (0.95)** | 0.11 | 30MB |

bt@16M reaches W-parity (0.99) with G now 9.2G; the remaining G gap to
vanilla's 5.76 total = residual per-object copy cost + full-GC marks
(the incremental-mature item). matmul remains default-only (burst > nursery;
pretenuring gate).

## D2/D3 (binarytrees pause streams, post UP-trace)

| config | pauses | total STW | p50 | p99 | max |
|--------|--------|-----------|-----|-----|-----|
| vanilla | 3554 | 1970ms | 0.04 | 3.6 | 15.2ms |
| Bactrian default | 57 | **1169ms** | 1.01 | 183 | 183ms |
| Bactrian @16M | 233 | 3081ms | 0.36 | 124 | 161ms |
| + conc-mark (dial) | 57 | 739ms | 0.71 | 98 | 98ms |
| + T=4 workers (dial) | 57 | ~1044ms | — | — | 146ms |

Aggregate STW firmly below vanilla; the pause TAIL (fulls) remains vanilla's
axis and the incremental-mature target.

## D4/D5 unchanged from addenda 8-10: RSS is nursery-residency-dominated
(vanilla kb 10MiB vs our 78 at default; @16M closes most); D5 frontier
crossover ~150-180MB; `MMTK_RELEASE_FREED_PAGES=1` is the opt-in footprint
dial (+0.9% cycles).

## Collection economics (the "why is G slower" answer, updated)

Pre-UP: 415 cy/object vs vanilla's 80 (5.2×), of which ~5.7 locked RMWs
≈ 170-230cy. Post-UP: locks 1.1/object; G@16M −25%. The remainder =
side-table addressing arithmetic, packet/queue machinery (the surviving
21M locks), SFT dispatch, and full-GC marks — next items, with incremental
mature reclamation still the structural one for the D3 tail.

## Integrity notes

All cells on fully-wiped rebuilds; the deploy pipeline's silent-fetch
failure mode (which produced two stale-build mismeasurements this session,
both caught and re-run) is now mitigated by visible fetch/reset in the
deploy sequence. Gates: byte-identical outputs incl. forced-concurrent,
T=4, and @16M variants. mmtk-core commits exist only as bundles until the
r41k0u/mmtk-core fork is created.
