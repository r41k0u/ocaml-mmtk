# Shape campaign RUNLOG — church, 2026-08-07T04:46:29+05:30
host: church |  04:46:29 up 1 day, 10:31,  1 user,  load average: 0.03, 0.20, 0.16
governor: powersave | paranoid: 4
fork:        6851ccfd4 runtime: account GC work done on the mutator thread (MMTK_MUTATOR_GC_TIME)
instruments: f83249b2a quick/threadcpu: fold the runtime's mutator-side GC time into a corrected D1
vanilla:     f5238509d (pristine 5.5.0)
pin: taskset -c 0-13 (one thread per physical core, socket 0); setarch -R on MMTk runs
operating point: MMTK_HEAP_SIZE_MB=192 vs vanilla o=500 (iso-memory, from the laptop D5 sweep)
[04:46:29] built gcpauses
[04:46:29] STAGE 1 heap sweep start
[05:03:46] STAGE 1 done: 50 cells
[05:03:46] STAGE 2 streams start
[05:05:39] STAGE 2 binarytrees done
[05:06:40] STAGE 2 kb done
[05:06:40] STAGE 3 M1 start
[05:07:11] STAGE 3 d=1 done
[05:07:32] STAGE 3 d=2 done
[05:07:50] STAGE 3 d=4 done
[05:08:11] STAGE 3 d=8 done
[05:09:03] STAGE 3 done
[05:09:03] campaign complete; packing
[05:10:00] TWEAKS: checkout shape/tweaks + rebuild
[05:10:01] HITCH: tweaks checkout failed
[05:11:24] TWEAKS: checkout shape/tweaks + rebuild
[05:12:26] TWEAKS: build done (12 natives)
[05:12:27] TWEAKS: correctness gate OK
[05:12:27] TWEAKS: matrix start
[05:13:00] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n2097152.c8 failed
[05:13:25] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n2097152.c28 failed
[05:13:48] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n2097152.c64 failed
[05:14:00] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n8388608.c8 failed
[05:14:11] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n8388608.c28 failed
[05:14:20] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n8388608.c64 failed
[05:14:26] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n33554432.c8 failed
[05:14:31] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n33554432.c28 failed
[05:14:35] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.n33554432.c64 failed
[05:14:39] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.ndefault.c8 failed
[05:14:43] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.ndefault.c28 failed
[05:14:47] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.binarytrees.ndefault.c64 failed
[05:15:12] TWEAKS: binarytrees matrix done
[05:15:19] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n2097152.c8 failed
[05:15:26] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n2097152.c28 failed
[05:15:33] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n2097152.c64 failed
[05:15:38] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n8388608.c8 failed
[05:15:44] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n8388608.c28 failed
[05:15:49] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n8388608.c64 failed
[05:15:52] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n33554432.c8 failed
[05:15:55] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n33554432.c28 failed
[05:15:58] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.n33554432.c64 failed
[05:16:01] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.ndefault.c8 failed
[05:16:03] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.ndefault.c28 failed
[05:16:06] HITCH: tweak cell /home/r41k0u/shape/results/20260807/streams/tweak.kb.ndefault.c64 failed
[05:16:12] TWEAKS: kb matrix done
[05:16:12] TWEAKS complete
[05:16:39] PAUSES: rerun of the stage-2/3 stall streams (mrun/vrun arg-order fix)
[05:17:50] PAUSES done
[05:17:51] PARFIX: rerun MMTk par threadcpu cells (per-TID sampler)
[05:18:40] PARFIX done
[05:19:31] PARFIX: rerun MMTk par threadcpu cells (per-TID sampler)
[05:20:18] PARFIX done
[05:23:26] VANPAUSE recapture done (interactive; detached-context corrupt-stream unresolved)

## Post-campaign notes (analysis session)

Hitches, in the order they were found and fixed:
1. Campaign script's mrun/vrun helpers had the benchmark ARG before the binary,
   so `env` tried to execute "20" — every stage-2/3 pause-stream run died
   instantly. cpu/rss/time data unaffected. Streams re-captured.
2. threadcpu (a) crashed after writing (NameError from a stale variable),
   logging phantom cell failures while data stayed valid; (b) needed per-TID
   accounting — par_binarytrees joins domains per depth class and a joined
   thread's CPU vanishes from /proc, so a d=2 cell summed 1.86 s where truth is
   ~4.2 s. MMTk par cpu cells re-run with the per-TID sampler (PARFIX).
3. gcpauses raises "Runtime_events: corrupt stream" when run from the DETACHED
   campaign context, but works flawlessly interactively (3554/3554 records) —
   UNRESOLVED; vanilla pause streams re-captured interactively.
4. The chained tweaks run initially failed at git fetch: no SSH agent in a
   detached watcher. Re-fetched with agent, relaunched without the fetch.
5. campaign_plots typo (zorder5) killed the summary write on first runs.

Retraction recorded: the 2026-08-06 claim that "idle MMTk workers park, so G is
roughly invariant to MMTK_THREADS" was an artifact of the pre-fix sampler
(worker CPU lost at thread exit). The per-TID data shows worker CPU GROWS with
T: binarytrees G = 1.74 (T=1) -> 3.34 (T=4). Workers burn CPU well beyond the
STW windows; mechanism (spin vs useful overlap) needs perf.
