#!/usr/bin/env python3
"""Quick panel (CLBG-style seq + kb + 3 adversarial): vanilla vs Bactrian gate vs v5.
Reads results/quick-vs-vanilla/panel.log; prints markdown tables; writes charts/quick_vs_vanilla.png.
Usage: quick_compare.py [results/quick-vs-vanilla] [charts]"""
import re, sys, os, glob
R = sys.argv[1] if len(sys.argv) > 1 else 'results/quick-vs-vanilla'; OUT = sys.argv[2] if len(sys.argv) > 2 else 'charts'
HOST = sys.argv[3] if len(sys.argv) > 3 else 'laptop P-cores'; PNG = sys.argv[4] if len(sys.argv) > 4 else 'quick_vs_vanilla.png'
BENCH = [(b, b.replace('_',' ')) for b in ['nbody','fannkuchredux','mandelbrot','spectralnorm','LU_decomposition','matrix_multiplication','binarytrees','kb','weak_memo','mature_mutation','fragmed']]
def parse(path, side):
    d = {}
    if not os.path.exists(path): return d
    for l in open(path):
        m = re.match(rf"{side} (\S+): (?:golden=\w+ )?wall_med=([0-9.]+)s \(n=[^)]*\) rss=(\d+)MB (?:pauses=(\d+) fulls=(\d+) max_pause=([0-9.]+)ms .*?GC time: (\d+) ms|minors=(\d+) majors=(\d+) promoted_words=\S+ gc_time=([0-9.?]+)s max_pause=([0-9.?]+)ms)", l)
        if not m: continue
        exe = m.group(1); w = float(m.group(2)); rss = int(m.group(3))
        if m.group(4):  # bactrian
            d[exe] = dict(wall=w, rss=rss, minors=int(m.group(4)) - int(m.group(5)), fulls=int(m.group(5)), maxp=float(m.group(6)), gc=int(m.group(7)) / 1000)
        else:
            d[exe] = dict(wall=w, rss=rss, minors=int(m.group(8)), fulls=int(m.group(9)), maxp=float(m.group(11)) if m.group(11) != '?' else None, gc=float(m.group(10)) if m.group(10) != '?' else None)
    return d
van = parse(f'{R}/panel.log', 'vanilla'); gate = parse(f'{R}/panel.log', 'gate-after'); v5 = parse(f'{R}/panel.log', 'gate-v5'); pre = {}
v5_filled = {}
for exe, _ in BENCH:
    if exe in v5: v5_filled[exe] = dict(v5[exe], filled=False)
    elif exe in gate: v5_filled[exe] = dict(gate[exe], filled=True)  # no sliced cycle occurs: identical to gate by construction
SERIES = [('vanilla', van), ('Bactrian gate (committed)', gate), ('Bactrian v5 (candidate)', v5_filled)]
def fmt(v, unit):
    if v is None: return '?'
    if unit == 's': return f'{v:.1f} s'
    if unit == 'MB': return f'{v/1024:.1f} GB' if v >= 1024 else f'{v:.0f} MB'
    if unit == 'ms': return f'{v/1000:.1f} s' if v >= 1000 else f'{v:.0f} ms'
    return f'{int(v):,}'
def table(key, unit, title, note=''):
    print(f'\n**{title}**\n')
    print('| bench | ' + ' | '.join(n for n, _ in SERIES) + ' | v5 ÷ vanilla |'); print('|---|' + '---:|' * (len(SERIES) + 1))
    for exe, name in BENCH:
        cells = []
        for n, d in SERIES:
            x = d.get(exe, {}).get(key); s = fmt(x, unit) + ('†' if d.get(exe, {}).get('filled') else '')
            cells.append(s)
        a = van.get(exe, {}).get(key); b = v5_filled.get(exe, {}).get(key)
        ratio = f'{b/a:.2f}×' if a and b else '?'
        print(f'| {name} | ' + ' | '.join(cells) + f' | {ratio} |')
    if note: print(f'\n{note}')
table('wall', 's', 'Wall time (median of 3)')
table('rss', 'MB', 'Peak RSS (max over the 3 timed runs)')
table('maxp', 'ms', 'Max pause', 'Bactrian: longest STW window in the pause log. Vanilla: `olly gc-stats` latency profile max.')
table('fulls', 'n', 'Major collections', 'Bactrian: Fulls plus completed sliced cycles. Vanilla: `major_collections` from `OCAMLRUNPARAM=v=0x400`.')
table('minors', 'n', 'Minor collections')
table('gc', 's', 'GC time', 'Bactrian: sum of STW time (`MMTK_VERBOSE`). Vanilla: `olly gc-stats` GC time (minor + major, incl. slices).')
pass
# ---- chart
try:
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; import numpy as np
except ImportError: sys.exit(0)
SURFACE='#ffffff'; TEXT1='#2b2f36'; TEXT2='#6b7280'; GRID='#e5e7eb'
COL={'vanilla':'#8a8f98','Bactrian gate (committed)':'#1baf7a','Bactrian v5 (candidate)':'#eb6834'}
def frame(ax):
    ax.set_facecolor(SURFACE)
    for s in ('top','right'): ax.spines[s].set_visible(False)
    for s in ('left','bottom'): ax.spines[s].set_color(GRID)
    ax.tick_params(colors=TEXT2, labelsize=8.5, length=0); ax.yaxis.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
panels=[('wall','Wall time, s',False),('rss','Peak RSS, MB',True),('maxp','Max pause, ms',True),('fulls','Major collections',True)]
fig, axes = plt.subplots(2, 2, figsize=(14, 8), dpi=150); fig.patch.set_facecolor(SURFACE)
series=[(n,d) for n,d in SERIES if n in COL]; W=0.26
for ax,(key,lab,log) in zip(axes.flat, panels):
    frame(ax); x=np.arange(len(BENCH))
    for i,(n,d) in enumerate(series):
        ys=[d.get(exe,{}).get(key) or np.nan for exe,_ in BENCH]
        bars=ax.bar(x+(i-1)*W, ys, W*0.92, color=COL[n], label=n, linewidth=0)
        if n=='Bactrian v5 (candidate)':  # label the candidate only; the gate ratios are in the tables
            for xi,(exe,_) in enumerate(BENCH):
                a=van.get(exe,{}).get(key); b=d.get(exe,{}).get(key)
                if a and b: ax.text(x[xi]+(i-1)*W, b*(1.08 if log else 1)+(0 if log else (ax.get_ylim()[1]*0.01)), f'{b/a:.1f}×', ha='center', va='bottom', fontsize=7, color=TEXT1)
    if log: ax.set_yscale('log')
    ax.set_xticks(x); ax.set_xticklabels([n for _,n in BENCH], fontsize=7.5, color=TEXT1, rotation=20, ha='right')
    ax.set_title(lab, fontsize=10.5, color=TEXT1, loc='left', pad=8)
h,l=axes[0][0].get_legend_handles_labels(); fig.legend(h,l,frameon=False,fontsize=8.5,labelcolor=TEXT1,loc='upper right',ncol=3,bbox_to_anchor=(0.99,0.965))
fig.suptitle(f'Quick panel (CLBG-style + kb + 3 adversarial), perf sizes, {HOST}, dynamic heap, 1 GC worker: vanilla vs Bactrian (labels = v5 ÷ vanilla)', fontsize=11, color=TEXT1, x=0.01, ha='left')
fig.tight_layout(rect=(0,0,1,0.92)); os.makedirs(OUT, exist_ok=True); fig.savefig(f'{OUT}/{PNG}', facecolor=SURFACE); print(f'\nchart: {OUT}/{PNG}')
