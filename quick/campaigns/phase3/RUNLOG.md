# Phase 3 definitive profile — church, 2026-08-07T16:13:48+05:30
governor: performance | paranoid: -1 | load: 0.00, 0.00, 0.00
fork: 5bb89af5a tweaks: MMTK_FULL_GC_CADENCE — make the full-GC cadence tunable for shape matching
instruments: 2c3cd81d7 quick/threadcpu: take the max across samples — thread exit erases its CPU
variants: vanilla (o=500 iso-memory; o=120 reference) vs Bactrian (192 MiB, T=1 seq / T=domains par)
pin: taskset -c 0-13; setarch -R on MMTk runs. ALL prior data was powersave; this supersedes.
[16:13:48] A: deep streams (binarytrees, kb): pause + rss + cpu + probe
[16:14:29] A: binarytrees done
[16:14:46] A: kb done
[16:14:46] B: D1 panel (8 benches): vanilla spans+time; Bactrian threadcpu x2
[16:16:04] B done
[16:16:04] C: perf counters panel (8 benches x both) + hybrid records (4 benches)
[16:17:08] C done
[16:17:08] D: D5 sweep (vanilla x overheads, Bactrian x heaps), performance governor
[16:27:15] D done: 32 cells
[16:27:15] E: M1 par_binarytrees d=1,2,4,8
[16:27:39] E: d=1 done
[16:27:53] E: d=2 done
[16:28:03] E: d=4 done
[16:28:14] E: d=8 done
[16:28:14] phase3 complete
