#!/usr/bin/env python3
"""threadcpu — D1 CPU budget without perf, and therefore without root.

D1 is the headline dimension: aggregate CPU doing work against aggregate CPU
doing GC, a ratio invariant to whether GC work is interleaved into the mutator
domains (vanilla) or handed to dedicated workers (Bactrian). Its proper
instrument is perf symbol attribution (see gcsplit.py), which asks "which code
ran" and so works identically on both runtimes. But perf needs
perf_event_paranoid lowered, which needs root, and root is not available on
every host we measure on.

This is the privilege-free route on the MMTk side. It works because on this
binding GC work runs on threads the mutator never uses, so per-thread CPU
separates the two directly:

    G  sum of utime+stime over threads named "mmtk-gc-worker"
    W  everything else (mutator domains, the main thread)

Both come from /proc/<pid>/task/<tid>/{comm,stat}, readable by the owning user
with no privileges at all.

The vanilla side is NOT this: vanilla has no GC threads, its major GC runs in
incremental slices ON the mutator domains, so thread attribution cannot see it.
There it comes from the runtime_events spans instead (lib/gcpauses.ml), whose
EV_MINOR + EV_MAJOR_SLICE durations ARE the on-mutator GC time. Different
mechanism per side, same definition — which is what the comparison needs.

WHAT THIS CANNOT DO, stated because it bounds the claim
------------------------------------------------------
Thread attribution cannot separate the C (coordination-spin) bucket from real
collector work: a worker spinning for work and a worker tracing are both
GC-thread CPU, and both land in G. perf can tell them apart by symbol; this
cannot.

Whether that matters is measurable rather than assumed. If MMTk's idle workers
PARK, worker CPU should be roughly invariant to MMTK_THREADS at fixed work; if
they SPIN, it will scale with worker count. Run --invariance to test it — and
note the result probes KC's framing directly, since the D1 ratio is supposed to
be invariant to how many threads the collector uses.

Sampling (rather than reading once at exit) also gives GC CPU over time, so D1
can be plotted against the D2/D3/D4 timelines instead of collapsing to a scalar.

Usage:
    threadcpu.py --out cpu.ndjson -- CMD ARGS...
    threadcpu.py --out cpu.ndjson --pid PID
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

CLK = os.sysconf("SC_CLK_TCK")          # jiffies per second
GC_THREAD_NAME = "mmtk-gc-worker"       # set in binding/src/collection.rs

# The runtime's report of GC work done ON the mutator thread (write barriers,
# TLAB refills, LOS allocations), emitted at exit under MMTK_MUTATOR_GC_TIME=1
# (runtime/mmtk.c). Without it, that work is misfiled as mutator CPU and the
# comparison against vanilla — whose span-based number captures ALL of its GC —
# flatters MMTk. Parked (blocked-for-GC) time is already excluded runtime-side.
MUT_GC_RE = re.compile(
    r"\[mmtk\] mutator GC time: ([\d.]+) ms \(barrier ([\d.]+) ms, "
    r"alloc ([\d.]+) ms; parked ([\d.]+) ms excluded\)")


def read_threads(pid):
    """{tid: (comm, utime_s, stime_s)} or None once the process is gone."""
    base = f"/proc/{pid}/task"
    try:
        tids = os.listdir(base)
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    out = {}
    for tid in tids:
        try:
            with open(f"{base}/{tid}/stat", "rb") as f:
                data = f.read()
            # comm is field 2 and may contain spaces or ')', so split on the
            # LAST ')': everything after it is positional and safe to split.
            rp = data.rindex(b")")
            comm = data[data.index(b"(") + 1:rp].decode("utf-8", "replace")
            rest = data[rp + 2:].split()
            # after state, fields are 1-indexed from ppid; utime=14, stime=15 of
            # the whole line, i.e. index 11 and 12 of `rest`.
            out[int(tid)] = (comm, int(rest[11]) / CLK, int(rest[12]) / CLK)
        except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
            continue        # thread exited mid-read; its final CPU is lost
    return out or None


def summarise(threads):
    g = w = 0.0
    ng = 0
    for _tid, (comm, ut, st) in threads.items():
        if comm == GC_THREAD_NAME:
            g += ut + st
            ng += 1
        else:
            w += ut + st
    return g, w, ng


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--interval-ms", type=float, default=20.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if (a.pid is None) == (not a.cmd):
        ap.error("give exactly one of --pid or -- CMD")
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd

    proc = None
    t0 = time.clock_gettime(time.CLOCK_MONOTONIC)
    with open(a.out, "w") as out:
        errf = None
        if a.pid is not None:
            pid = a.pid
        else:
            # Arm the runtime's mutator-side accounting and keep stderr so the
            # at-exit line can be folded into the summary. A file, not a pipe:
            # a filling pipe would deadlock the child while we sleep.
            env = dict(os.environ, MMTK_MUTATOR_GC_TIME="1")
            errf = tempfile.TemporaryFile()
            proc = subprocess.Popen(cmd, start_new_session=True, env=env,
                                    stderr=errf)
            pid = proc.pid

        # Per-TID accounting, not a max of the instantaneous sum. A thread's
        # accumulated CPU vanishes from /proc/<pid>/task the moment it exits,
        # and OCaml programs join and respawn DOMAINS mid-run (par_binarytrees
        # spawns a fresh set per depth class) — so the instantaneous sum both
        # drops on every join and never includes already-dead threads. Observed:
        # a d=2 run whose true mutator CPU is ~4.5 s summed to 0.5 s. Each TID's
        # own CPU is monotone while it lives, so we keep the max ever seen PER
        # TID and sum over every thread that ever existed; a death freezes its
        # contribution. Residual loss: under one sampling interval per thread.
        seen = {}                       # tid -> (comm, max cpu seen)
        def fold(th):
            for tid, (comm, ut, st) in th.items():
                cur = ut + st
                old = seen.get(tid)
                if old is None or cur > old[1]:
                    seen[tid] = (comm, cur)
        while True:
            if proc is not None and proc.poll() is not None:
                break
            th = read_threads(pid)
            if th is None:
                break
            fold(th)
            g, w, ng = summarise(th)
        g, w, ng = best_g, best_w, best_ng
        tot = g + w
        summary = {
            "kind": "cpu_summary",
            "gc_cpu_s": round(g, 4),
            "mutator_cpu_s": round(w, 4),
            "total_cpu_s": round(tot, 4),
            # Raw thread-attributed ratio. G here is workers only and bundles
            # coordination-spin; see the module docstring.
            "gc_fraction": round(g / tot, 5) if tot else None,
            "gc_threads": ng,
            "wall_s": round(wall, 4),
            "exit": rc,
        }
        if errf is not None:
            errf.seek(0)
            text = errf.read().decode("utf-8", "replace")
            errf.close()
            sys.stderr.write(text)          # preserve the child's stderr
            m = MUT_GC_RE.search(text)
            if m:
                mg = float(m.group(1)) / 1e3
                gc_c = g + mg
                w_c = max(0.0, w - mg)
                summary.update({
                    "mut_gc_s": round(mg, 4),
                    "mut_gc_barrier_s": round(float(m.group(2)) / 1e3, 4),
                    "mut_gc_alloc_s": round(float(m.group(3)) / 1e3, 4),
                    "parked_s": round(float(m.group(4)) / 1e3, 4),
                    # Corrected split: mutator-side GC work moved into G. This
                    # is the number to compare against vanilla's span-based one.
                    "gc_corrected_s": round(gc_c, 4),
                    "mutator_corrected_s": round(w_c, 4),
                    "gc_fraction_corrected":
                        round(gc_c / tot, 5) if tot else None,
                })
        out.write(json.dumps(summary) + "\n")

    if tot:
        print(f"  GC {g:.2f}s  mutator {w:.2f}s  total {tot:.2f}s  "
              f"gc_fraction {g/tot:.4f}  ({ng} GC threads, wall {wall:.2f}s)")
    else:
        print("  no CPU recorded")
    sys.exit(rc if rc else 0)


if __name__ == "__main__":
    main()
