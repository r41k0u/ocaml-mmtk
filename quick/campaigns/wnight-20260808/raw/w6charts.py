#!/usr/bin/env python3
"""v6 comprehensive-campaign charts (D1-D5 + attribution), dataviz-compliant.

Palette roles (validated reference palette, light mode):
  S1 blue #2a78d6 = vanilla, S2 orange #eb6834 = Bactrian default,
  S3 aqua #1baf7a = Bactrian @2M, S4 amber #eda100 = Bactrian +UP-oldify
  diverging: #2a78d6 below 1.0 / #e34948 above, baseline #c3c2b7
  surface #fcfcfb; text always ink/secondary, never series color.
"""
import json, math, os, re, statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.expanduser("~/shape/wcomp6")
V3R = os.path.expanduser("~/shape/wcomp4/v3reuse")
FIG = os.path.join(OUT, "figs"); os.makedirs(FIG, exist_ok=True)

SURFACE="#fcfcfb"; INK="#0b0b0b"; SEC="#52514e"; MUTED="#898781"
GRID="#e1e0d9"; BASE="#c3c2b7"
S1,S2,S3,S4 = "#2a78d6","#eb6834","#1baf7a","#eda100"
DIV_LO,DIV_HI = "#2a78d6","#e34948"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.edgecolor": BASE, "axes.labelcolor": SEC,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "grid.color": GRID, "grid.linewidth": 0.6,
    "font.family": "sans-serif", "font.size": 10,
    "axes.titlecolor": INK, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
})

BENCHES = ["binarytrees","nbody","fannkuchredux","spectralnorm","mandelbrot",
           "matrix_multiplication","LU_decomposition","kb","mature_mutation",
           "weak_memo","fragmed"]
SHORT = {"binarytrees":"binarytrees","nbody":"nbody","fannkuchredux":"fannkuch",
         "spectralnorm":"spectralnorm","mandelbrot":"mandelbrot",
         "matrix_multiplication":"matmul","LU_decomposition":"LU","kb":"kb",
         "mature_mutation":"mature-mut","weak_memo":"weak-memo","fragmed":"fragmed"}

def med(tag, ev):
    vals=[]
    for r in (1,2,3):
        p=f"{OUT}/{tag}.r{r}.stat"
        if not os.path.exists(p): continue
        for line in open(p):
            f=line.split(",")
            if len(f)>=3 and f[2]==ev:
                try: vals.append(float(f[0]))
                except ValueError: pass
    return st.median(vals) if vals else None

def ndjson(path):
    if not os.path.exists(path): return []
    out=[]
    for l in open(path):
        l=l.strip()
        if not l: continue
        try: out.append(json.loads(l))
        except ValueError: pass
    return out

# ---- fig1: D1 grouped diverging ratio bars (default + oldify vs 1.0) ----
def fig1():
    names, rd, ro = [], [], []
    for b in BENCHES:
        v,d,o = med(f"v.{b}","cycles"), med(f"d.{b}","cycles"), med(f"o.{b}","cycles")
        if v and d:
            names.append(SHORT[b]); rd.append(d/v); ro.append((o/v) if o else None)
    fig, ax = plt.subplots(figsize=(8.4, 5.4))
    for i,(r1,r2) in enumerate(zip(rd,ro)):
        c1 = DIV_HI if r1>1.0 else DIV_LO
        ax.barh(i-0.19, r1-1.0, left=1.0, height=0.34, color=c1, zorder=3)
        ax.annotate(f"{r1:.2f}", xy=(r1,i-0.19), xytext=(5 if r1>=1 else -5,0),
                    textcoords="offset points", va="center",
                    ha="left" if r1>=1 else "right", color=INK, fontsize=8)
        if r2:
            c2 = DIV_HI if r2>1.0 else DIV_LO
            ax.barh(i+0.19, r2-1.0, left=1.0, height=0.34, color=c2, alpha=0.45, zorder=3)
            ax.annotate(f"{r2:.2f}", xy=(r2,i+0.19), xytext=(5 if r2>=1 else -5,0),
                        textcoords="offset points", va="center",
                        ha="left" if r2>=1 else "right", color=SEC, fontsize=8)
    ax.axvline(1.0, color=BASE, lw=1.2, zorder=2)
    ax.set_yticks(range(len(names))); ax.set_yticklabels(names, color=SEC)
    ax.invert_yaxis()
    hi = max(max(rd), max(r for r in ro if r))
    ax.set_xlim(0.72, min(hi+0.35, 5.4))
    ax.set_xlabel("whole-process cycles vs vanilla (1.0 = parity; solid = default, faded = +UP-oldify)")
    ax.set_title("D1 — CPU budget: Bactrian / vanilla cycle ratio (192 MiB heap)")
    ax.grid(axis="x", zorder=0)
    fig.tight_layout(); fig.savefig(f"{FIG}/fig1_d1_ratios.png", dpi=150); plt.close(fig)

# ---- fig2: D2 pacing (cumulative STW time vs wall time, + cycle counts) ----
def majors_of(b, tag):
    if tag.startswith("v"):
        for r in ndjson(f"{OUT}/streams/v.{b}.probe.ndjson"):
            if r.get("kind")=="summary": return r.get("final_major_collections")
        return None
    m=re.search(r"full: (\d+)", open(f"{OUT}/streams/{tag}.verbose").read())
    return int(m.group(1)) if m else None

def fig2():
    fig, axes = plt.subplots(2, 2, figsize=(9.6, 6.8))
    for ax, b in zip(axes.flat, ("binarytrees","kb","LU_decomposition","spectralnorm")):
        for tag,color,label in ((f"v.{b}",S1,"vanilla (o=500)"),
                                (f"d.{b}",S2,"Bactrian default (n16)"),
                                (f"dn2.{b}",S3,"Bactrian @2M")):
            recs=[r for r in ndjson(f"{OUT}/streams/{tag}.pause.ndjson") if "dur" in r]
            if not recs: continue
            t0=recs[0].get("at",0.0)
            xs,[ys,acc]=[0.0],[[0.0],0.0]
            for r in recs:
                xs.append(r.get("at",0.0)-t0); ys.append(acc)
                acc+=r["dur"]*1e3
                xs.append(r.get("at",0.0)-t0); ys.append(acc)
            nmaj=majors_of(b, tag)
            lbl=f"{label}" + (f" — {nmaj} majors" if nmaj is not None else "")
            ax.plot(xs, ys, color=color, lw=2, label=lbl, zorder=3)
        ax.set_xlabel("wall time (s)")
        ax.set_title(f"D2 — GC pacing: {SHORT[b]}")
        ax.grid(zorder=0)
        ax.legend(frameon=False, labelcolor=SEC, fontsize=8, loc="upper left")
    for ax in axes[:,0]: ax.set_ylabel("cumulative STW time (ms)")
    fig.tight_layout(); fig.savefig(f"{FIG}/fig2_d2_pacing.png", dpi=150); plt.close(fig)

# ---- fig3: D3 pause CDFs (5 benches + summary panel) ----
def fig3():
    order=("binarytrees","kb","LU_decomposition","spectralnorm","mature_mutation")
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 7.0))
    for ax, b in zip(axes.flat, order):
        for tag,color,label in ((f"v.{b}",S1,"vanilla"),
                                (f"d.{b}",S2,"Bactrian default (n16)"),
                                (f"dn2.{b}",S3,"Bactrian @2M")):
            durs=sorted(r["dur"]*1e3 for r in ndjson(f"{OUT}/streams/{tag}.pause.ndjson") if "dur" in r)
            if not durs: continue
            n=len(durs)
            ax.plot(durs, [i/n for i in range(1,n+1)], color=color, lw=2,
                    label=f"{label} (max {durs[-1]:.1f})", zorder=3)
        ax.set_xscale("log")
        ax.set_xlabel("pause (ms, log)")
        ax.set_title(f"D3 — pause CDF: {SHORT[b]}")
        ax.grid(zorder=0)
        ax.legend(frameon=False, labelcolor=SEC, fontsize=7.5, loc="upper left")
    axes.flat[5].axis("off")
    axes.flat[5].text(0.02, 0.65,
        "Reading: right = longer pauses.\n"
        "@2M is the stock-parity latency dial:\n"
        "sliced cycles cap mark work per pause.\n"
        "n16 default trades pause size for D1\n"
        "throughput (promotion-bound minors).",
        color=SEC, fontsize=9, va="top")
    for ax in axes[:,0]: ax.set_ylabel("fraction of pauses ≤ x")
    fig.tight_layout(); fig.savefig(f"{FIG}/fig3_d3_cdf.png", dpi=150); plt.close(fig)

# ---- fig4: D4 RSS over time (dynamic heap = memory parity) ----
def fig4():
    order=("binarytrees","kb","LU_decomposition","spectralnorm","mature_mutation")
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 6.6))
    for ax, b in zip(axes.flat, order):
        for tag,color,label in ((f"v.{b}",S1,"vanilla"),(f"d.{b}",S2,"Bactrian")):
            recs=[r for r in ndjson(f"{OUT}/streams/{tag}.rss.ndjson") if r.get("kind")=="rss"]
            if not recs: continue
            t0=recs[0].get("t",0)
            ax.plot([r.get("t",0)-t0 for r in recs],
                    [r.get("rss",0)/1048576 for r in recs],
                    color=color, lw=2, label=label, zorder=3)
        ax.set_xlabel("wall time (s)")
        ax.set_title(f"D4 — RSS: {SHORT[b]} (dynamic heap)")
        ax.grid(zorder=0)
    axes.flat[5].axis("off")
    axes.flat[0].legend(frameon=False, labelcolor=SEC, fontsize=9)
    for ax in axes[:,0]: ax.set_ylabel("RSS (MiB)")
    fig.tight_layout(); fig.savefig(f"{FIG}/fig4_d4_rss.png", dpi=150); plt.close(fig)

# ---- fig5: D5 pareto frontier (v6 Bactrian cells + v3 vanilla cells) ----
def front(pts):
    pts=sorted(pts); out=[]
    best=float("inf")
    for rss,wall in pts:
        if wall<best: out.append((rss,wall)); best=wall
    return out

def fig5():
    dpts=ndjson(f"{OUT}/pareto.ndjson")
    vpts=[r for r in ndjson(f"{V3R}/pareto_merged.ndjson") if r.get("side")=="v"]
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0))
    for ax, b in zip(axes, ("kb","binarytrees")):
        for side,src,color,label in (("v",vpts,S1,"vanilla (o / s sweep)"),
                                     ("d",dpts,S2,"Bactrian (heap × nursery sweep)")):
            pts=[(r["rss_kb"]/1024, r["wall_s"]) for r in src if r.get("bench")==b]
            if not pts: continue
            f=front(pts)
            ax.scatter([p[0] for p in pts],[p[1] for p in pts], s=14, color=color,
                       alpha=0.35, zorder=2, edgecolors="none")
            ax.plot([p[0] for p in f],[p[1] for p in f], color=color, lw=2,
                    marker="o", ms=4, label=label, zorder=3)
        ax.set_xlabel("peak RSS (MiB)")
        ax.set_title(f"D5 — space–time frontier: {SHORT[b]}")
        ax.grid(zorder=0)
        ax.legend(frameon=False, labelcolor=SEC, fontsize=8)
    axes[0].set_ylabel("wall time (s)")
    fig.tight_layout(); fig.savefig(f"{FIG}/fig5_d5_frontier.png", dpi=150); plt.close(fig)

# ---- fig6: attribution A/B (oldify off vs on), stacked per-object cycles ----
BUCKETS = [
    ("intrinsic copy", S1, ["memmove","memcpy","copy_nonoverlapping","attempt_to_forward",
                            "forward_object","Line::is_marked","mark_lines"]),
    ("binding scan/slot", S2, ["mmtk_ocaml","FieldSlot","scan_ocaml","VMScanning",
                               "scan_object","up_oldify"]),
    ("drain loop (plan)", S3, ["bactrian","Bactrian","concurrent_marking_work",
                               "ConcurrentTraceObjects","PlanScanObjects"]),
    ("mmtk-core machinery", S4, ["SideMetadataSpec","MetadataSpec","side_metadata","gc_work",
                                 "scheduler","work_bucket","CopySpace","immixspace",
                                 "ImmixAllocator","alloc","GCWorkerCopyContext",
                                 "VectorQueue","enqueue","policy","trace_object"]),
]
def classify(sym):
    for name,_,pats in BUCKETS:
        for p in pats:
            if re.search(p,sym): return name
    return "mmtk-core machinery"

def attr_one(k):
    shares={}
    for line in open(f"{OUT}/attr.{k}.worker.txt"):
        m=re.match(r"\s+([0-9.]+)%\s+(?:\S+\s+)+?\[\.\]\s+(.*)", line)
        if not m: continue
        pct,sym=float(m.group(1)),m.group(2)
        cl=classify(sym); shares[cl]=shares.get(cl,0)+pct
    total=sum(shares.values())
    whole=None
    for line in open(f"{OUT}/attr.{k}.whole"):
        f=line.split(",")
        if len(f)>=3 and f[2]=="cycles": whole=float(f[0])
    ws=float(open(f"{OUT}/attr.{k}.wshare").read().strip())/100
    copied=int(re.search(r"objects copied: (\d+)", open(f"{OUT}/attr.{k}.verbose").read()).group(1))
    per=whole*ws/copied
    return {n:(v/total)*per for n,v in shares.items()}, per

def fig6():
    fig, ax = plt.subplots(figsize=(8.6, 3.2))
    rows=[("UP-oldify ON (opt-in)",1),("generic drain (default)",0)]
    colors={b[0]:b[1] for b in BUCKETS}
    order=[b[0] for b in BUCKETS]
    for y,(label,k) in enumerate(rows):
        vals,per=attr_one(k)
        left=0.0
        for name in order:
            v=vals.get(name,0)
            ax.barh(y, v, left=left, height=0.52, color=colors[name],
                    edgecolor=SURFACE, linewidth=2, zorder=3,
                    label=name if y==0 else None)
            if v>per*0.09:
                ax.annotate(f"{v:.0f}", xy=(left+v/2,y), ha="center", va="center",
                            color=SURFACE, fontsize=8, fontweight="bold")
            left+=v
        ax.annotate(f"{label}  ≈{per:.0f} cy/obj", xy=(left+6,y), va="center",
                    color=SEC, fontsize=9)
    ax.set_yticks([]); ax.set_xlim(0, 520)
    ax.set_xlabel("cycles per promoted object (binarytrees @ 8 MiB nursery)")
    ax.set_title("Per-object collection cost — attribution, UP-oldify A/B")
    ax.grid(axis="x", zorder=0)
    ax.legend(frameon=False, labelcolor=SEC, fontsize=8, ncol=4,
              loc="upper center", bbox_to_anchor=(0.5,-0.28))
    fig.tight_layout(); fig.savefig(f"{FIG}/fig6_attribution.png", dpi=150); plt.close(fig)

if __name__ == "__main__":
    fig1(); fig2(); fig3(); fig4(); fig5(); fig6()
    print("figs:", sorted(os.listdir(FIG)))
