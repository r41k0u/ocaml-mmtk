#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""campaign_plots — comparative figures for a full shape campaign.

Consumes a results directory produced by the church campaign script:

    sweep.ndjson                          D5 (quickbench heap sweep, --gc)
    streams/<bench>.<variant>.<knob>.pause.ndjson   D3 stalls
        vanilla: gcpauses records {phase: minor|major_slice|major_stw}
        MMTk:    MMTK_PAUSE_LOG records {full: bool}
    streams/*.rss.ndjson                  D4 timelines (rss_sampler)
    streams/*.cpu<i>.ndjson               D1 corrected splits (threadcpu)
    streams/*.time.txt                    wall/user/sys/maxRSS lines (vanilla, par)
    streams/*.probe.ndjson                D2 pacing samples
    streams/*.stderr                      MMTk at-exit lines ([mmtk] GCs, mutator GC time)

Emits PNGs into <results>/graphs plus shape_summary.md with the numbers behind
the pictures.

MMU here is computed from the AUTHORITATIVE stall streams (pause logs / spans),
not probe gaps — the probe's coarse placement cannot resolve stalls on
binarytrees (see SHAPE.md). "Stall" means the same thing on both sides: an
interval in which the mutator makes no program progress (MMTk: parked in STW;
vanilla: stopped for a minor, or running a major slice instead of the program).
For multi-domain runs the union across domains is used ("some mutator stalled");
this is exact for MMTk (STW stops all domains) and conservative for vanilla.
"""

import glob
import json
import os
import re
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

C = {"vanilla": "#444444", "GenImmix": "#4C72B0", "Bactrian": "#8172B3"}
RESULTS = sys.argv[1] if len(sys.argv) > 1 else "."
GRAPHS = os.path.join(RESULTS, "graphs")
os.makedirs(GRAPHS, exist_ok=True)
S = os.path.join(RESULTS, "streams")
report = []


def rep(line=""):
    report.append(line)
    print(line)


def nd(path):
    out = []
    if not os.path.exists(path):
        return out
    for l in open(path):
        l = l.strip()
        if l:
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                pass
    return out


def save(fig, name):
    p = os.path.join(GRAPHS, name)
    fig.tight_layout()
    fig.savefig(p, dpi=130)
    plt.close(fig)
    print(f"  wrote {p}")


# ---------------- stalls / MMU ----------------
def stalls_of(path):
    """[(start, dur)] union-merged, plus t_end, from either record shape."""
    recs = [r for r in nd(path) if r.get("kind") == "pause"]
    iv = sorted((r["at"], r["at"] + r["dur"]) for r in recs)
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    t_end = merged[-1][1] if merged else 1.0
    return [(a, b - a) for a, b in merged], t_end, recs


def mmu(stalls, t_end, w):
    if t_end <= w:
        tot = sum(d for _, d in stalls)
        return max(0.0, 1.0 - tot / max(t_end, 1e-9))
    cands = {0.0}
    for s, d in stalls:
        for t in (s, s - w, s + d - w):
            if 0.0 <= t <= t_end - w:
                cands.add(t)
    def util(t):
        st = 0.0
        for s, d in stalls:
            if s + d <= t or s >= t + w:
                continue
            st += min(s + d, t + w) - max(s, t)
        return 1.0 - st / w
    return max(0.0, min(util(t) for t in cands))


# ---------------- per-bench figures ----------------
def bench_figs(bench):
    variants = [("vanilla", f"{bench}.vanilla.o500"),
                ("GenImmix", f"{bench}.GenImmix.T4"),
                ("Bactrian", f"{bench}.Bactrian.T4")]

    # D3 pause CDFs
    fig, ax = plt.subplots(figsize=(7, 4.5))
    any_data = False
    for label, pfx in variants:
        _, _, recs = stalls_of(os.path.join(S, pfx + ".pause.ndjson"))
        if not recs:
            continue
        any_data = True
        if label == "vanilla":
            groups = {}
            for r in recs:
                groups.setdefault(r.get("phase", "?"), []).append(r["dur"] * 1e3)
            styles = {"minor": "-", "major_slice": ":", "major_stw": "--"}
            for ph, d in groups.items():
                d.sort()
                ax.plot(d, [i / len(d) for i in range(len(d))],
                        styles.get(ph, "-"), color=C[label],
                        label=f"vanilla {ph} (n={len(d)})")
        else:
            for full, style in ((False, "-"), (True, "--")):
                d = sorted(r["dur"] * 1e3 for r in recs if r.get("full") == full)
                if d:
                    ax.plot(d, [i / len(d) for i in range(len(d))], style,
                            color=C[label],
                            label=f"{label} {'full' if full else 'nursery'} (n={len(d)})")
    if any_data:
        ax.set_xscale("log")
        ax.set_xlabel("stall duration (ms)")
        ax.set_ylabel("cumulative fraction")
        ax.set_title(f"D3 stall distribution — {bench}")
        ax.legend(fontsize=7)
        ax.grid(alpha=.3)
        save(fig, f"d3_cdf_{bench}.png")
    else:
        plt.close(fig)

    # D3 MMU
    ws = [1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 3e-1, 1.0]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    rep(f"\n### D3 {bench}: MMU (authoritative stall streams)")
    rep("| variant | stalls | stalled s | MMU@1ms | MMU@10ms | MMU@100ms |")
    rep("|---|---|---|---|---|---|")
    for label, pfx in variants:
        st, t_end, recs = stalls_of(os.path.join(S, pfx + ".pause.ndjson"))
        if not recs:
            continue
        curve = [mmu(st, t_end, w) for w in ws]
        ax.plot(ws, curve, marker="o", color=C[label], label=label)
        rep(f"| {label} | {len(recs)} | {sum(d for _, d in st):.2f} | "
            f"{mmu(st, t_end, 1e-3):.3f} | {mmu(st, t_end, 1e-2):.3f} | "
            f"{mmu(st, t_end, 1e-1):.3f} |")
    ax.set_xscale("log")
    ax.set_xlabel("window (s)")
    ax.set_ylabel("minimum mutator utilization")
    ax.set_ylim(-.02, 1.02)
    ax.set_title(f"D3 MMU — {bench} (union of stall streams)")
    ax.legend()
    ax.grid(alpha=.3)
    save(fig, f"d3_mmu_{bench}.png")

    # D4 RSS timelines
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for label, pfx in variants:
        rs = [r for r in nd(os.path.join(S, pfx + ".rss.ndjson")) if r.get("kind") == "rss"]
        if rs:
            ax.plot([r["t"] for r in rs], [r["rss"] / 2**20 for r in rs],
                    lw=1.1, color=C[label], label=label)
    ax.set_xlabel("wall time (s)")
    ax.set_ylabel("RSS (MiB)")
    ax.set_title(f"D4 footprint over time — {bench} (iso-memory operating point)")
    ax.legend()
    ax.grid(alpha=.3)
    save(fig, f"d4_rss_{bench}.png")

    # D2 pacing (probe samples)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    got = False
    for label, pf in (("vanilla", f"{bench}.vanilla.probe.ndjson"),
                      ("GenImmix", f"{bench}.GenImmix.probe.ndjson"),
                      ("Bactrian", f"{bench}.Bactrian.probe.ndjson")):
        sm = [r for r in nd(os.path.join(S, pf)) if r.get("kind") == "sample"]
        if sm:
            got = True
            ax.plot([r["minor_words"] * 8 / 2**20 for r in sm],
                    [r["major_collections"] for r in sm],
                    marker=".", color=C[label], label=label)
    if got:
        ax.set_xlabel("cumulative allocation (MiB, minor path)")
        ax.set_ylabel("cumulative major collections")
        ax.set_title(f"D2 pacing — {bench}")
        ax.legend()
        ax.grid(alpha=.3)
        save(fig, f"d2_pacing_{bench}.png")
    else:
        plt.close(fig)


# ---------------- D1 stacked bars ----------------
def d1_fig():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=False)
    rep("\n### D1 corrected CPU budget (G = collector incl. mutator-side GC; W = program)")
    rep("| bench | variant | G s | W s | fraction |")
    rep("|---|---|---|---|---|")
    for ax, bench in zip(axes, ("binarytrees", "kb")):
        labels, Gs, Ws = [], [], []
        # vanilla o=500: G = span sum (pause stream), CPU = median of time.txt
        tt = os.path.join(S, f"{bench}.vanilla.o500.time.txt")
        st, _, recs = stalls_of(os.path.join(S, f"{bench}.vanilla.o500.pause.ndjson"))
        if os.path.exists(tt) and recs:
            cpus = []
            for line in open(tt):
                p = line.split()
                if len(p) >= 3:
                    cpus.append(float(p[1]) + float(p[2]))
            cpu = statistics.median(cpus)
            g = sum(r["dur"] for r in recs)
            labels.append("vanilla\no=500"); Gs.append(g); Ws.append(max(0, cpu - g))
            rep(f"| {bench} | vanilla o=500 | {g:.2f} | {cpu - g:.2f} | {g/cpu:.3f} |")
        for plan in ("GenImmix", "Bactrian"):
            for T in (1, 4):
                gs, ws_ = [], []
                for f in glob.glob(os.path.join(S, f"{bench}.{plan}.T{T}.cpu*.ndjson")):
                    summ = [r for r in nd(f) if r.get("kind") == "cpu_summary"]
                    if summ and summ[0].get("gc_corrected_s") is not None \
                       and summ[0]["gc_cpu_s"] > 0:
                        gs.append(summ[0]["gc_corrected_s"])
                        ws_.append(summ[0]["mutator_corrected_s"])
                if gs:
                    g, w = statistics.median(gs), statistics.median(ws_)
                    labels.append(f"{plan}\nT={T}"); Gs.append(g); Ws.append(w)
                    rep(f"| {bench} | {plan} T={T} | {g:.2f} | {w:.2f} | {g/(g+w):.3f} |")
        x = range(len(labels))
        ax.bar(x, Ws, color="#AAAAAA", label="W (program)")
        ax.bar(x, Gs, bottom=Ws, color="#C44E52", label="G (collector)")
        for i, (g, w) in enumerate(zip(Gs, Ws)):
            ax.text(i, g + w + .05, f"{g/(g+w):.2f}", ha="center", fontsize=8)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylabel("CPU seconds")
        ax.set_title(bench)
        ax.grid(alpha=.3, axis="y")
    axes[0].legend(fontsize=8)
    fig.suptitle("D1 CPU budget, corrected (number atop bar = GC fraction)")
    save(fig, "d1_cpu_budget.png")


# ---------------- D5 ----------------
def d5_fig():
    rows = nd(os.path.join(RESULTS, "sweep.ndjson"))
    for bench in ("binarytrees", "kb"):
        fig, ax = plt.subplots(figsize=(7.5, 5))
        for var, color in (("vanilla", C["vanilla"]),
                           ("mmtk:GenImmix", C["GenImmix"]),
                           ("mmtk:Bactrian", C["Bactrian"])):
            s = sorted((r for r in rows if r.get("bench") == bench
                        and r.get("variant") == var and r.get("status") == "ok"
                        and r.get("rss_mib")),
                       key=lambda r: r["rss_mib"])
            if not s:
                continue
            ax.plot([r["rss_mib"] for r in s], [r["median_ms"] for r in s],
                    marker="o", color=color, label=var)
            for r in s:
                k = r.get("heap") or (r.get("ocamlrunparam") or "")
                ax.annotate(str(k), (r["rss_mib"], r["median_ms"]), fontsize=6,
                            xytext=(3, 3), textcoords="offset points", color=color)
        ax.set_xlabel("measured peak RSS (MiB)")
        ax.set_ylabel("median wall (ms)")
        ax.set_title(f"D5 space-time — {bench} (church, interleaved reps)")
        ax.legend()
        ax.grid(alpha=.3)
        save(fig, f"d5_{bench}.png")


# ---------------- M1 ----------------
def m1_fig():
    doms = [1, 2, 4, 8]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    rep("\n### M1 par_binarytrees domain sweep")
    rep("| variant | d | wall s | total CPU s | GCs | stalled s |")
    rep("|---|---|---|---|---|---|")
    series = {}
    for var in ("vanilla", "GenImmix", "Bactrian"):
        walls, cpus, gcs, stall = [], [], [], []
        for d in doms:
            pfx = os.path.join(S, f"par_binarytrees.{var}.d{d}")
            wall = cpu = None
            tt = pfx + ".time.txt"
            if os.path.exists(tt):
                ws_, cs = [], []
                for line in open(tt):
                    p = line.split()
                    if len(p) >= 3:
                        ws_.append(float(p[0])); cs.append(float(p[1]) + float(p[2]))
                if ws_:
                    wall, cpu = statistics.median(ws_), statistics.median(cs)
            for f in glob.glob(pfx + ".cpu*.ndjson"):
                summ = [r for r in nd(f) if r.get("kind") == "cpu_summary"]
                if summ:
                    wall = wall or summ[0]["wall_s"]
                    cpu = summ[0]["total_cpu_s"]
            n_gc = None
            err = pfx + ".stderr"
            if os.path.exists(err):
                m = re.search(r"GCs: (\d+)", open(err).read())
                if m:
                    n_gc = int(m.group(1))
            st, _, recs = stalls_of(pfx + ".pause.ndjson")
            sstall = sum(x for _, x in st) if recs else None
            walls.append(wall); cpus.append(cpu); gcs.append(n_gc); stall.append(sstall)
            rep(f"| {var} | {d} | {wall if wall else '-'} | "
                f"{f'{cpu:.2f}' if cpu else '-'} | {n_gc if n_gc is not None else '-'} | "
                f"{f'{sstall:.2f}' if sstall is not None else '-'} |")
        series[var] = (walls, cpus, gcs)
    for var, (walls, cpus, gcs) in series.items():
        if walls[0]:
            axes[0].plot(doms, [walls[0] / w if w else None for w in walls],
                         marker="o", color=C[var], label=var)
        axes[1].plot(doms, cpus, marker="o", color=C[var], label=var)
        axes[2].plot(doms, gcs, marker="o", color=C[var], label=var)
    axes[0].plot(doms, doms, "k:", alpha=.4, label="ideal")
    for ax, t, yl in ((axes[0], "speedup", "T(1)/T(d)"),
                      (axes[1], "total CPU", "CPU s"),
                      (axes[2], "collections", "GCs")):
        ax.set_xlabel("domains"); ax.set_ylabel(yl); ax.set_title(t)
        ax.grid(alpha=.3); ax.legend(fontsize=8)
    fig.suptitle("M1 — par_binarytrees across domains (strong scaling)")
    save(fig, "m1_scaling.png")


def main():
    rep(f"# Shape campaign summary — {RESULTS}")
    d5_fig()
    d1_fig()
    for b in ("binarytrees", "kb"):
        bench_figs(b)
    m1_fig()
    with open(os.path.join(RESULTS, "shape_summary.md"), "w") as f:
        f.write("\n".join(report) + "\n")
    print(f"\nwrote {RESULTS}/shape_summary.md")


if __name__ == "__main__":
    main()
