#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""shapeplot — turn the probe / pause-log / RSS streams into the shape graphs.

Run with `uv run lib/shapeplot.py ...`, as with quickbench.py: the inline
PEP-723 block pulls matplotlib into a throwaway env rather than requiring it on
the system interpreter.

Consumes what the instruments emit:
    <prefix>.probe.ndjson   in-mutator probe   (D2 samples, D3 gaps)
    <prefix>.pause.ndjson   MMTK_PAUSE_LOG     (D3 attribution, MMTk only)
    <prefix>.rss.ndjson     rss_sampler.py     (D4)

Usage:
    shapeplot.py --run vanilla=out/van --run Bactrian=out/bac --out graphs/

Produces, per run overlaid on shared axes:
    1  pacing      cumulative GC events vs cumulative MiB allocated        (D2)
    2  mmu         minimum mutator utilization vs window width, log x      (D3a/b)
    3  util_time   u(t,w) over wall time at two fixed w                    (D3c)
    4  rss_time    RSS vs wall time — the sawtooth                         (D4)
    5  cpu_budget  stacked W / G / C                                       (D1)

On MMU
------
MMU(w) is the MINIMUM over all window positions of the fraction of that window
in which the mutator was running. Sliding, not binned: a fixed grid would split
a pause across a boundary and each half would look benign, whereas the quantity
wanted is the worst alignment — MMU is a guarantee ("over ANY window of width w
you get at least this much"), so the worst case is the whole point.

The minimum over a continuum is computed exactly rather than sampled: the worst
window always has a stall boundary at one of its edges, so evaluating at every
stall start (and every stall end minus w) finds the true minimum.

Because a pure minimum is hostage to one unlucky window, the 1st-percentile
utilization is drawn alongside it — that says whether bad windows are rare or
pervasive, which the minimum alone cannot.
"""

import argparse
import bisect
import json
import os
import sys


def read_ndjson(path):
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue      # tolerate a truncated tail from a killed run
    return out


class Stalls:
    """Stall intervals plus a prefix sum, for O(log n) 'stalled time in [a,b]'."""

    def __init__(self, intervals, t_end):
        self.iv = sorted(intervals)
        self.t_end = t_end
        self.starts = [s for s, _ in self.iv]
        self.cum = [0.0]
        for s, d in self.iv:
            self.cum.append(self.cum[-1] + d)

    def stalled_in(self, a, b):
        """Total stall time overlapping [a, b]."""
        if b <= a or not self.iv:
            return 0.0
        i = bisect.bisect_left(self.starts, a)
        # An interval starting before `a` may still overlap it.
        total = 0.0
        if i > 0:
            s, d = self.iv[i - 1]
            total += max(0.0, min(s + d, b) - max(s, a))
        while i < len(self.iv):
            s, d = self.iv[i]
            if s >= b:
                break
            total += max(0.0, min(s + d, b) - max(s, a))
            i += 1
        return total

    def utilization_at(self, t, w):
        if w <= 0:
            return 1.0
        return max(0.0, 1.0 - self.stalled_in(t, t + w) / w)

    def candidates(self, w):
        """Window starts that can realise the minimum: each stall's start (worst
        case the window opens exactly on a stall) and each stall's end minus w
        (worst case it closes exactly as one ends)."""
        cs = {0.0}
        for s, d in self.iv:
            for t in (s, s - w, s + d - w):
                if 0.0 <= t <= max(0.0, self.t_end - w):
                    cs.add(t)
        return sorted(cs)

    def mmu(self, w):
        if self.t_end <= w:
            return self.utilization_at(0.0, self.t_end)
        return min(self.utilization_at(t, w) for t in self.candidates(w))

    def util_percentile(self, w, q=1.0, n=400):
        """q-th percentile utilization over evenly spaced windows."""
        if self.t_end <= w:
            return self.utilization_at(0.0, self.t_end)
        span = self.t_end - w
        vals = sorted(self.utilization_at(span * i / (n - 1), w) for i in range(n))
        return vals[max(0, min(len(vals) - 1, int(q / 100.0 * len(vals))))]

    def series(self, w, n=600):
        span = max(1e-9, self.t_end - w)
        xs = [span * i / (n - 1) for i in range(n)]
        return xs, [self.utilization_at(t, w) for t in xs]


def load_run(label, prefix):
    probe = read_ndjson(prefix + ".probe.ndjson")
    pause = read_ndjson(prefix + ".pause.ndjson")
    rss = read_ndjson(prefix + ".rss.ndjson")

    gaps = [(r["at"], r["dur"]) for r in probe if r.get("kind") == "gap"]
    samples = [r for r in probe if r.get("kind") == "sample"]
    # The probe's timeline is absolute wall clock; rebase it on its own start so
    # runs of different lengths and start times can share an x axis.
    t0 = min([a for a, _ in gaps] + [s["at"] for s in samples], default=0.0)
    gaps = [(a - t0, d) for a, d in gaps]
    for s in samples:
        s["t"] = s["at"] - t0
    t_end = max([a + d for a, d in gaps] + [s["t"] for s in samples], default=1.0)

    return dict(label=label, gaps=gaps, samples=samples,
                pauses=[r for r in pause if r.get("kind") == "pause"],
                rss=[r for r in rss if r.get("kind") == "rss"],
                stalls=Stalls(gaps, t_end), t_end=t_end)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", default=[], metavar="LABEL=PREFIX",
                    help="a run; reads <PREFIX>.{probe,pause,rss}.ndjson")
    ap.add_argument("--out", default="graphs")
    ap.add_argument("--windows", default="0.0001,0.001,0.01,0.1,1.0",
                    help="MMU window widths in seconds")
    ap.add_argument("--util-windows", default="0.01,0.1",
                    help="fixed widths for the utilization-over-time plot")
    a = ap.parse_args()
    if not a.run:
        ap.error("give at least one --run LABEL=PREFIX")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs = []
    for spec in a.run:
        if "=" not in spec:
            ap.error(f"--run wants LABEL=PREFIX, got {spec!r}")
        label, prefix = spec.split("=", 1)
        runs.append(load_run(label, prefix))
    os.makedirs(a.out, exist_ok=True)
    ws = [float(x) for x in a.windows.split(",")]
    uws = [float(x) for x in a.util_windows.split(",")]

    def save(fig, name):
        p = os.path.join(a.out, name)
        fig.tight_layout()
        fig.savefig(p, dpi=130)
        plt.close(fig)
        print(f"  wrote {p}")

    # 1 — D2 pacing: the SLOPE is the pacing law. A straight line means
    # allocation-paced (vanilla's design); steps mean pressure-triggered bursts.
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for r in runs:
        if not r["samples"]:
            continue
        x = [s["minor_words"] * 8 / 2**20 for s in r["samples"]]
        y = [s["major_collections"] for s in r["samples"]]
        ax.plot(x, y, marker=".", label=r["label"])
    ax.set_xlabel("cumulative allocation (MiB, minor-heap path)")
    ax.set_ylabel("cumulative major collections")
    ax.set_title("D2 pacing — GC events vs allocation")
    ax.legend(); ax.grid(alpha=.3)
    save(fig, "d2_pacing.png")

    # 2 — D3 MMU, with the 1st-percentile line: the minimum alone is hostage to
    # a single unlucky window, the percentile says whether bad windows are rare.
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for r in runs:
        line, = ax.plot(ws, [r["stalls"].mmu(w) for w in ws],
                        marker="o", label=f"{r['label']} MMU")
        ax.plot(ws, [r["stalls"].util_percentile(w, 1.0) for w in ws],
                marker="^", ls="--", color=line.get_color(), alpha=.6,
                label=f"{r['label']} p1")
    ax.set_xscale("log")
    ax.set_xlabel("window width (s)")
    ax.set_ylabel("mutator utilization")
    ax.set_ylim(-0.02, 1.02)
    ax.set_title("D3 minimum mutator utilization (solid) and 1st percentile (dashed)")
    ax.legend(fontsize=8); ax.grid(alpha=.3)
    save(fig, "d3_mmu.png")

    # 3 — D3c utilization over time: distinguishes a sustained depression
    # (permanently mid-cycle) from periodic dips, which MMU cannot express.
    fig, axes = plt.subplots(len(uws), 1, figsize=(8, 3 * len(uws)), squeeze=False)
    for ax, w in zip(axes[:, 0], uws):
        for r in runs:
            xs, ys = r["stalls"].series(w)
            ax.plot(xs, ys, lw=.9, label=r["label"])
        ax.set_ylabel(f"util (w={w*1000:g} ms)")
        ax.set_ylim(-0.02, 1.02); ax.grid(alpha=.3); ax.legend(fontsize=8)
    axes[-1, 0].set_xlabel("wall time (s)")
    axes[0, 0].set_title("D3c mutator utilization over time")
    save(fig, "d3_util_time.png")

    # 4 — D4 footprint: equal PEAK RSS can hide opposite curves.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for r in runs:
        if not r["rss"]:
            continue
        ax.plot([s["t"] for s in r["rss"]], [s["rss"] / 2**20 for s in r["rss"]],
                lw=1.1, label=r["label"])
    ax.set_xlabel("wall time (s)"); ax.set_ylabel("RSS (MiB)")
    ax.set_title("D4 footprint over time")
    ax.legend(); ax.grid(alpha=.3)
    save(fig, "d4_rss_time.png")

    # 5 — D3 pause distribution, split nursery vs full. The split is the finding:
    # concurrent marking moves the FULL-GC pause, and may leave the tail (nursery)
    # untouched.
    fig, ax = plt.subplots(figsize=(7, 4.5))
    any_p = False
    for r in runs:
        for full, style in ((False, "-"), (True, "--")):
            d = sorted(p["dur"] * 1000 for p in r["pauses"] if p["full"] == full)
            if not d:
                continue
            any_p = True
            ax.plot(d, [i / len(d) for i in range(len(d))], style,
                    label=f"{r['label']} {'full' if full else 'nursery'}")
    if any_p:
        ax.set_xscale("log")
        ax.set_xlabel("pause (ms)"); ax.set_ylabel("cumulative fraction")
        ax.set_title("D3 GC pause distribution (MMTk side)")
        ax.legend(fontsize=8); ax.grid(alpha=.3)
        save(fig, "d3_pause_cdf.png")
    else:
        plt.close(fig)

    # Console summary — the numbers behind the pictures.
    print("\nshape summary")
    print(f"  {'run':16}{'wall s':>8}{'stall s':>9}{'stall%':>8}"
          f"{'MMU@10ms':>10}{'p1@10ms':>9}{'GCs':>6}{'peakRSS':>9}")
    for r in runs:
        stall = sum(d for _, d in r["gaps"])
        peak = max((s["rss"] for s in r["rss"]), default=0) / 2**20
        print(f"  {r['label']:16}{r['t_end']:8.2f}{stall:9.2f}"
              f"{100*stall/max(r['t_end'],1e-9):8.1f}"
              f"{r['stalls'].mmu(0.01):10.3f}{r['stalls'].util_percentile(0.01):9.3f}"
              f"{len(r['pauses']):6d}{peak:9.1f}")


if __name__ == "__main__":
    main()
