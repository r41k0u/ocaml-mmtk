#!/usr/bin/env python3
"""eio RSS over time: results/eio-rss/{e1,e2}/<label>.rss (t_s rss_MB) + <label>.pause.ndjson.
Usage: eio_rss_charts.py results/eio-rss charts"""
import sys, os, json, glob
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
R = sys.argv[1] if len(sys.argv) > 1 else 'results/eio-rss'; OUT = sys.argv[2] if len(sys.argv) > 2 else 'charts'
SURFACE='#ffffff'; TEXT1='#2b2f36'; TEXT2='#6b7280'; GRID='#e5e7eb'
COL = {'vanilla':'#8a8f98','pregate':'#6b5cd6','gate':'#1baf7a','v5':'#eb6834','nc':'#1baf7a','ov50':'#eb6834','nur2':'#6b5cd6','heap4g':'#c9a227','rate01':'#3b82f6'}
NAME = {'vanilla':'vanilla','pregate':'Bactrian pre-gate','gate':'Bactrian gate','v5':'Bactrian v5','nc':'v5, all cycles monolithic (BACTRIAN_NO_CONCURRENT)','ov50':'v5, margin 50 % (MMTK_MATURE_OVERHEAD_PCT=50)','nur2':'v5, 2 MB nursery','heap4g':'v5, heap pinned 4 GB'}
def frame(ax):
    ax.set_facecolor(SURFACE)
    for s in ('top','right'): ax.spines[s].set_visible(False)
    for s in ('left','bottom'): ax.spines[s].set_color(GRID)
    ax.tick_params(colors=TEXT2, labelsize=8.5, length=0); ax.yaxis.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
def load(d, label):
    f = os.path.join(d, label + '.rss')
    if not os.path.exists(f): return None, []
    pts = [tuple(map(float, l.split())) for l in open(f) if l.strip()]
    pl = os.path.join(d, label + '.pause.ndjson'); fulls = []
    if os.path.exists(pl):
        p = [json.loads(l) for l in open(pl) if l.startswith('{')]
        fulls = [x['at'] for x in p if x.get('kind') == 'pause' and x.get('full')]
    return pts, fulls
for panel, labels, title in [('e1', ['vanilla','pregate','gate','v5'], 'eio_conc_bench: RSS over time, vanilla vs Bactrian variants (ticks = Full / FinalMark pauses)'),
                              ('e2', ['nc','ov50','nur2','heap4g'], 'eio_conc_bench under Bactrian v5: one knob at a time (ticks = Full / FinalMark pauses)')]:
    d = os.path.join(R, panel); fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150); fig.patch.set_facecolor(SURFACE); frame(ax)
    ymax = 0
    for i, lab in enumerate(labels):
        pts, fulls = load(d, lab)
        if not pts: continue
        xs = [p[0] for p in pts]; ys = [p[1] / 1024 for p in pts]; ymax = max(ymax, max(ys))
        ax.plot(xs, ys, color=COL[lab], linewidth=1.8, label=f'{NAME[lab]}  (peak {max(ys):.1f} GB)')
        for t in fulls: ax.plot([t, t], [-(0.02 + 0.02 * i) * 1, -(0.005 + 0.02 * i)], color=COL[lab], linewidth=0.6, transform=ax.get_xaxis_transform(), clip_on=False)
    ax.set_ylim(0, ymax * 1.08); ax.set_xlabel('time, s', fontsize=9.5, color=TEXT1); ax.set_ylabel('resident set, GB', fontsize=9.5, color=TEXT1)
    ax.set_title(title, fontsize=10.5, color=TEXT1, loc='left', pad=10); ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXT1, loc='upper left')
    fig.tight_layout(); os.makedirs(OUT, exist_ok=True); fig.savefig(os.path.join(OUT, f'eio_rss_{panel}.png'), facecolor=SURFACE); print('chart:', os.path.join(OUT, f'eio_rss_{panel}.png'))

# ---- E3: instrumented v5 run — what the heap trigger sees vs what is resident
import json as _json
sj = os.path.join(R, 'e3', 'v5dbg.series.json'); pl = os.path.join(R, 'e3', 'v5dbg.pause.ndjson'); rf = os.path.join(R, 'e3', 'v5dbg.rss')
if os.path.exists(sj) and os.path.exists(pl) and os.path.exists(rf):
    ev = _json.load(open(sj)); p = [x for x in (_json.loads(l) for l in open(pl) if l.startswith('{')) if x.get('kind') == 'pause']
    n = min(len(ev), len(p)); t = [p[i]['at'] for i in range(n)]
    fig, ax = plt.subplots(figsize=(11, 5.4), dpi=150); fig.patch.set_facecolor(SURFACE); frame(ax)
    rss = [tuple(map(float, l.split())) for l in open(rf) if l.strip()]
    ax.plot([r[0] for r in rss], [r[1] / 1024 for r in rss], color='#8a8f98', linewidth=1.6, label='resident set (RSS)')
    ax.plot(t, [ev[i]['reserved'] / 1024 for i in range(n)], color='#eb6834', linewidth=1.6, label='reserved pages (what the trigger calls "live")')
    ax.plot(t, [ev[i]['heap'] / 1024 for i in range(n)], color='#1baf7a', linewidth=1.6, label='heap limit = 2.2 × reserved, raised after every minor')
    for i in range(n):
        if ev[i]['pause'] == 'InitialMark': ax.axvline(t[i], color='#6b5cd6', linewidth=0.9, linestyle='--')
        if ev[i]['pause'] == 'FinalMark': ax.axvline(t[i], color='#6b5cd6', linewidth=0.9)
    sw = [(t[i], ev[i]['sweep']) for i in range(n)]
    on = None
    for x, s in sw:
        if s and on is None: on = x
        if not s and on is not None: ax.axvspan(on, x, color='#6b5cd6', alpha=0.08, linewidth=0); on = None
    if on is not None: ax.axvspan(on, t[n-1], color='#6b5cd6', alpha=0.08, linewidth=0)
    ax.axhline(2.1, color='#8a8f98', linewidth=0.8, linestyle=':'); ax.text(t[n-1], 2.2, 'vanilla peak heap 2.1 GB', fontsize=8, color=TEXT2, ha='right')
    ax.set_xlabel('time, s', fontsize=9.5, color=TEXT1); ax.set_ylabel('GB', fontsize=9.5, color=TEXT1)
    ax.set_title('eio under Bactrian v5: the heap limit chases the unswept mature space\n(dashed = InitialMark, solid = FinalMark, shaded = deferred sweep in progress, during which no new cycle can start)', fontsize=9.5, color=TEXT1, loc='left', pad=10)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=TEXT1, loc='upper left'); fig.tight_layout(); fig.savefig(os.path.join(OUT, 'eio_rss_e3.png'), facecolor=SURFACE); print('chart:', os.path.join(OUT, 'eio_rss_e3.png'))
