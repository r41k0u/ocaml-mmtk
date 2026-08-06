#!/usr/bin/env python3
"""rss_sampler — D4 footprint-over-time: sample a process's RSS while it runs.

Only *peak* RSS exists anywhere in this tree today (quickbench's ru_maxrss).
Peak cannot distinguish two collectors with the same high-water mark but
opposite curves — which is exactly the vanilla/Bactrian case, since vanilla
sweeps incrementally and reclaims continuously while Bactrian holds garbage
until FinalMark. D4 needs the curve, so this samples it.

WHY /proc/<pid>/statm AND NOT smaps_rollup
------------------------------------------
smaps_rollup walks every VMA and its page-table entries while holding the
target's mmap_lock. MMTk maps a very large virtual range for side metadata, so
that walk is expensive *and* it blocks the target — it would perturb the thing
being measured, in any language. statm reads precomputed counters
(mm->total_vm, get_mm_rss()); the lock is held for microseconds. The sampler
being Python was never the risk; the /proc file was.

Cost: one open/read/close of a small file per sample, in a separate process on
a different core. At the 10 ms default that is ~100 reads/s, well under 0.2% of
one core. The overhead gate (bare / +probe / +sampler / +both) is what actually
settles this; if it ever shows up, this is ~40 lines of C.

Output: NDJSON, one record per sample, flushed as it goes so a killed run keeps
everything sampled so far.

Usage:
    rss_sampler.py --pid PID --out FILE [--interval-ms 10]
    rss_sampler.py --out FILE -- CMD ARGS...      # spawn and follow
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time

PAGE = os.sysconf("SC_PAGE_SIZE")


def read_statm(pid):
    """(rss_bytes, vsize_bytes), or None once the process is gone or a zombie.

    A finished child is not removed from /proc until it is reaped: it becomes a
    zombie, and a zombie's statm reads as all zeros rather than failing to open.
    Treating that as a live sample of 0 bytes made the first version of this
    loop spin forever, so all-zero is an exit condition, not a data point.
    """
    try:
        with open(f"/proc/{pid}/statm", "rb") as f:
            parts = f.read().split()
        size, resident = int(parts[0]), int(parts[1])
        if size == 0 and resident == 0:
            return None  # zombie
        return resident * PAGE, size * PAGE
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        return None


def sample_loop(pid, out, interval_s, t0, is_alive=None):
    """Sample until the process exits. Returns (peak_rss, n_samples).

    Timestamps use CLOCK_MONOTONIC so they are directly comparable with the
    in-mutator probe's timeline, and are recorded as an offset from t0 so the
    two streams can be aligned.

    Exit is detected two ways because neither alone is sufficient: statm going
    away or reading all-zero (covers --pid, where we cannot wait()), and the
    caller's is_alive (covers the spawn case, where the child is a zombie we
    have not reaped yet).
    """
    peak = 0
    n = 0
    while True:
        if is_alive is not None and not is_alive():
            break
        got = read_statm(pid)
        if got is None:
            break
        rss, vsz = got
        peak = max(peak, rss)
        n += 1
        out.write(json.dumps({
            "kind": "rss",
            "t": time.clock_gettime(time.CLOCK_MONOTONIC) - t0,
            "rss": rss,
            "vsz": vsz,
        }) + "\n")
        out.flush()
        time.sleep(interval_s)
    return peak, n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, help="sample an already-running process")
    ap.add_argument("--out", required=True, help="NDJSON output path")
    ap.add_argument("--interval-ms", type=float, default=10.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="-- CMD ARGS: spawn CMD and sample it")
    a = ap.parse_args()

    if (a.pid is None) == (not a.cmd):
        ap.error("give exactly one of --pid or -- CMD")

    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    interval_s = a.interval_ms / 1000.0
    proc = None
    t0 = time.clock_gettime(time.CLOCK_MONOTONIC)

    with open(a.out, "w") as out:
        if a.pid is not None:
            pid = a.pid
        else:
            # start_new_session so a stray signal to us cannot orphan the child's
            # process group — the tree has been bitten by orphaned groups before.
            proc = subprocess.Popen(cmd, start_new_session=True)
            pid = proc.pid

        try:
            peak, n = sample_loop(pid, out, interval_s, t0)
        except KeyboardInterrupt:
            if proc is not None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            raise

        rc = proc.wait() if proc is not None else None
        out.write(json.dumps({
            "kind": "rss_summary",
            "samples": n,
            "peak_rss": peak,
            "interval_ms": a.interval_ms,
            "wall": time.clock_gettime(time.CLOCK_MONOTONIC) - t0,
            "exit": rc,
        }) + "\n")

    sys.exit(rc if rc else 0)


if __name__ == "__main__":
    main()
