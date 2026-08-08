#!/usr/bin/env python3
"""W-night figures — consumes the wnight1..4 result directories (rsynced from
church) and emits the morning-report charts into a campaign directory.

Usage: wnight_figs.py <results_root> <out_dir>
where <results_root> contains wnight1/ wnight2/ wnight3/ wnight3b/ wnight4/.
"""
import os
import statistics as st
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = sys.argv[1]
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)

VAN, BAC, ACC = "#4878d0", "#d65f5f", "#59a14f"


def perf(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path):
        if line.startswith("#") or not line.strip():
            continue
        f = line.split(",")
        if len(f) < 3:
            continue
        try:
            d[f[2]] = float(f[0])
        except ValueError:
            continue
    return d


def med(rnd, tag, ev):
    vals = []
    for r in (1, 2, 3):
        d = perf(os.path.join(ROOT, rnd, f"{tag}.r{r}.perf"))
        if ev in d:
            vals.append(d[ev])
    return st.median(vals) if vals else None


BENCHES = ["binarytrees", "nbody", "fannkuchredux", "spectralnorm",
           "mandelbrot", "matrix_multiplication", "LU_decomposition", "kb"]
SHORT = {"binarytrees": "bintr", "nbody": "nbody", "fannkuchredux": "fannk",
         "spectralnorm": "spect", "mandelbrot": "mandl",
         "matrix_multiplication": "matmul", "LU_decomposition": "LU", "kb": "kb"}

# ---- fig 1: cycle + instruction ratios, stock vs new defaults --------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
xs = range(len(BENCHES))
for ax, ev, title in ((ax1, "cycles", "cycle ratio (Bactrian / vanilla)"),
                      (ax2, "instructions", "instruction ratio")):
    stock, newdef = [], []
    for b in BENCHES:
        v3 = med("wnight3", f"v.{b}", ev)
        b3 = med("wnight3", f"b.{b}", ev)
        v4 = med("wnight4", f"v.{b}", ev)
        d4 = med("wnight4", f"d.{b}", ev)
        stock.append(b3 / v3 if v3 and b3 else float("nan"))
        newdef.append(d4 / v4 if v4 and d4 else float("nan"))
    w = 0.38
    ax.bar([x - w / 2 for x in xs], stock, w, color=BAC, alpha=0.55,
           label="stock Bactrian")
    ax.bar([x + w / 2 for x in xs], newdef, w, color=ACC,
           label="new defaults (jitter+THP)")
    ax.axhline(1.0, color="k", lw=1, ls="--")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([SHORT[b] for b in BENCHES], rotation=45)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
ax1.set_ylabel("ratio vs vanilla (1.0 = parity)")
ax1.legend(fontsize=9)
fig.suptitle("W-night: whole-process ratios before/after the night's fixes "
             "(church, heap 192 MiB, T=1, cores 0-13)")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig1_ratios.png"), dpi=140)
plt.close(fig)

# ---- fig 2: matmul LLC story ----------------------------------------------
fig, ax = plt.subplots(figsize=(8, 4.5))
cfgs = [("vanilla", "wnight1", "v.mm768", VAN),
        ("Bactrian stock", "wnight1", "b.mm768", BAC),
        ("LOS ≥ 2KB", "wnight1", "los2k.mm768", "#b07aa1"),
        ("jitter 5-bit", "wnight2", "jit2.mm768", "#f28e2b"),
        ("jitter 6-bit\n(new default)", "wnight3", "j6.matrix_multiplication", ACC)]
names = [c[0] for c in cfgs]
vals = [med(c[1], c[2], "LLC-loads") / 1e6 for c in cfgs]
bars = ax.bar(names, vals, color=[c[3] for c in cfgs])
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v * 1.04, f"{v:.0f}M",
            ha="center", fontsize=9)
ax.set_yscale("log")
ax.set_ylabel("LLC-loads (millions, log)")
ax.set_title("matmul-768: allocation-pitch L2 aliasing — cause and fix\n"
             "(LOS routing makes it worse: page-aligned pitch has zero entropy)")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig2_matmul_llc.png"), dpi=140)
plt.close(fig)

# ---- fig 3: nursery curves -------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
sizes = [2, 4, 8, 16, 32, 64]
bt_wall, bt_ins = [], []
for s in sizes:
    tag = f"nur{s}.bt20" if s != 64 else "b.bt20"
    bt_wall.append(med("wnight1", tag, "duration_time") / 1e9)
    bt_ins.append(med("wnight1", tag, "instructions") / 1e9)
ax1.plot(sizes, bt_wall, "o-", color=BAC, label="wall (s)")
ax1.set_xscale("log", base=2)
ax1.set_xlabel("nursery (MiB)")
ax1.set_ylabel("wall (s)", color=BAC)
ax1b = ax1.twinx()
ax1b.plot(sizes, bt_ins, "s--", color="#b07aa1", label="instructions (G)")
ax1b.set_ylabel("instructions (G)", color="#b07aa1")
van_wall = med("wnight1", "v.bt20", "duration_time") / 1e9
ax1.axhline(van_wall, color=VAN, lw=1.2, ls=":", label="vanilla wall")
ax1.set_title("binarytrees: small nursery = premature promotion\n"
              "-> full-GC storms (6 -> 186 fulls), 9.5x instructions")
ax1.legend(fontsize=8, loc="upper right")
lu_cm, lu_cyc = [], []
for s in sizes:
    rnd = "wnight2" if s != 64 else "wnight1"
    tag = f"nur{s}.lu900" if s != 64 else "b.lu900"
    lu_cm.append(med(rnd, tag, "cache-misses") / 1e6)
    lu_cyc.append(med(rnd, tag, "cycles") / 1e9)
ax2.plot(sizes, lu_cm, "o-", color=BAC, label="cache-misses (M)")
ax2.set_xscale("log", base=2)
ax2.set_yscale("log")
ax2.set_xlabel("nursery (MiB)")
ax2.set_ylabel("demand cache-misses (M, log)", color=BAC)
ax2b = ax2.twinx()
ax2b.plot(sizes, lu_cyc, "s--", color="#b07aa1")
ax2b.set_ylabel("cycles (G)", color="#b07aa1")
ax2.set_title("LU: the store frontier — DRAM traffic vanishes at ≤8 MiB\n"
              "(155M -> 0.3M) but OoO had hidden most of its latency")
ax2.legend(fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig3_nursery.png"), dpi=140)
plt.close(fig)

# ---- fig 4: stall decomposition -------------------------------------------
fig, ax = plt.subplots(figsize=(8, 4.5))
cells = [("vanilla bt", "s.v.bt20", VAN), ("Bactrian bt", "s.b.bt20", BAC),
         ("vanilla kb", "s.v.kb50", VAN), ("Bactrian kb", "s.b.kb50", BAC)]
names = [c[0] for c in cells]
shares, ipcs = [], []
for _, tag, _ in cells:
    d = perf(os.path.join(ROOT, "wnight3b", f"{tag}.r1.perf"))
    shares.append(100 * d.get("cycle_activity.stalls_mem_any", 0)
                  / d.get("cycles", 1))
    ipcs.append(d.get("instructions", 0) / d.get("cycles", 1))
bars = ax.bar(names, shares, color=[c[2] for c in cells], alpha=0.8)
for b, sh, ipc in zip(bars, shares, ipcs):
    ax.text(b.get_x() + b.get_width() / 2, sh + 0.3,
            f"{sh:.1f}%\nIPC {ipc:.2f}", ha="center", fontsize=9)
ax.set_ylabel("% of cycles stalled on memory (stalls_mem_any)")
ax.set_title("The residual W-tax is STORE-side: Bactrian's loads hit L1 at "
             "98.9%,\nyet memory stalls double — cold-frontier bump stores "
             "drain at RFO latency")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig4_stalls.png"), dpi=140)
plt.close(fig)

# ---- fig 5: M1 with new defaults ------------------------------------------
have_par = all(os.path.exists(os.path.join(ROOT, "wnight4", f"par.d{d}.r1.perf"))
               for d in (1, 2, 4, 8))
if have_par:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    doms = [1, 2, 4, 8]
    bwall, vwall = [], []
    for d in doms:
        bw = [perf(os.path.join(ROOT, "wnight4", f"par.d{d}.r{r}.perf"))
              .get("duration_time") for r in (1, 2)]
        vw = [perf(os.path.join(ROOT, "wnight4", f"vpar.d{d}.r{r}.perf"))
              .get("duration_time") for r in (1, 2)]
        bwall.append(st.median([x for x in bw if x]) / 1e9)
        vwall.append(st.median([x for x in vw if x]) / 1e9)
    ax.plot(doms, vwall, "o-", color=VAN, label="vanilla")
    ax.plot(doms, bwall, "s-", color=ACC, label="Bactrian new defaults (T=d)")
    ax.set_xscale("log", base=2)
    ax.set_xticks(doms)
    ax.set_xticklabels(doms)
    ax.set_xlabel("domains")
    ax.set_ylabel("wall (s)")
    ax.set_title("par_binarytrees 20: M1 scaling with the new defaults\n"
                 "(workers = domains, heap 448 MiB)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig5_m1.png"), dpi=140)
    plt.close(fig)

print(f"figures written to {OUT}")
