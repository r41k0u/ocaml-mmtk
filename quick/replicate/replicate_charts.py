#!/usr/bin/env python3
"""Regenerate the presentation charts from replicate.sh's raw results.

Usage: replicate_charts.py <results-dir> <charts-dir>

Produces (matching the presentation):
  d1_ratios.png      - D1 cycle ratios, panel benches
  d1_adversarial.png - D1 including the adversarial pair
  d2_count.png       - major-collection counts, Bactrian @2M vs Vanilla
  d3_curve.png       - cumulative STW over the run (Bactrian streams; Vanilla
                       cumulative needs its instrumented stream and is drawn
                       only if v.*.pause.ndjson files are present)
  d4_rss.png         - peak RSS, both runtimes
  d5_scatter.png     - space-time scatter over the configuration grids
Falls back to wall-clock ratios automatically when perf data is absent.
"""
import json, math, pathlib, statistics, sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

R = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
SURFACE='#fcfcfb'; TEXT1='#0b0b0b'; TEXT2='#52514e'; GRID='#e8e7e4'
ORANGE='#eb6834'; AQUA='#1baf7a'; MUTED='#e8a091'

PANEL=['weak_memo','fannkuchredux','nbody','mandelbrot','matrix_multiplication',
       'kb','spectralnorm','binarytrees','LU_decomposition']
SHORT={'weak_memo':'weak_\nmemo','fannkuchredux':'fannkuch','nbody':'nbody',
       'mandelbrot':'mandelbrot','matrix_multiplication':'matmul','kb':'kb',
       'spectralnorm':'spectralnorm','binarytrees':'binarytrees',
       'LU_decomposition':'LU','mature_mutation':'mature_\nmutation','fragmed':'fragmed'}
ADV=['mature_mutation','fragmed']

def ev(f, name):
    for line in open(f):
        if f',{name},' in line:
            return int(line.split(',')[0])
def metric(prefix, b):
    """median cycles (perf) or median wall seconds (fallback); returns (value, kind)."""
    stats=[R/f'{prefix}.{b}.r{r}.stat' for r in (1,2,3)]
    if all(s.exists() for s in stats):
        return statistics.median(ev(s,'cycles') for s in stats), 'cycles'
    walls=[R/f'{prefix}.{b}.r{r}.wall' for r in (1,2,3)]
    if all(w.exists() for w in walls):
        return statistics.median(float(open(w).read().split()[-1]) for w in walls), 'wall'
    return None, None
def rss(prefix, b):
    f=R/f'{prefix}.{b}.rss'
    return int(open(f).read().split()[-1])/1024 if f.exists() else None

def frame(ax):
    ax.set_facecolor(SURFACE)
    ax.yaxis.grid(True,color=GRID,linewidth=0.8); ax.set_axisbelow(True)
    for s in ('top','right','left'): ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(GRID); ax.tick_params(colors=TEXT2,length=0)
def bar(ax,x,h,c,w):
    ax.add_patch(FancyBboxPatch((x-w/2,0),w,h,boxstyle="round,pad=0,rounding_size=0.02",
        mutation_aspect=w/0.04,linewidth=0,facecolor=c))

# ---- D1 ----
def d1(names, fname, title):
    vals=[]; kind='cycles'
    for b in names:
        v,k1=metric('v',b); d,k2=metric('d',b)
        if v and d: vals.append((b,d/v)); kind=k1
    if not vals: return
    fig,ax=plt.subplots(figsize=(max(6,1.1*len(vals)),5.0),dpi=150)
    fig.patch.set_facecolor(SURFACE); frame(ax)
    top=max(v for _,v in vals)
    for i,(b,r) in enumerate(vals):
        bar(ax,i,r,MUTED if b in ADV else ORANGE,0.6)
        ax.text(i,r+top*0.02,f'{r:.2f}',ha='center',fontsize=9.5,color=TEXT2)
    ax.axhline(1.0,color=TEXT2,linewidth=1,linestyle=(0,(4,3)),alpha=0.6)
    ax.set_xticks(range(len(vals))); ax.set_xticklabels([SHORT[b] for b,_ in vals],fontsize=8.6,color=TEXT1)
    ax.set_ylabel(f'{kind} vs Vanilla (lower is better)',fontsize=9.5,color=TEXT1)
    ax.set_ylim(0,top*1.15); ax.set_xlim(-0.7,len(vals)-0.3)
    ax.set_title(title,fontsize=12,color=TEXT1,loc='left',pad=12,fontweight='bold')
    g=math.exp(sum(math.log(v) for _,v in vals)/len(vals))
    ax.text(len(vals)-0.35,top*1.08,f'geomean {g:.2f}',ha='right',fontsize=9,color=TEXT2)
    plt.tight_layout(); plt.savefig(OUT/fname,facecolor=SURFACE); plt.close()
d1(PANEL,'d1_ratios.png','D1 - CPU cost: Bactrian (+UP-oldify) vs Vanilla')
d1(PANEL+ADV,'d1_adversarial.png','D1 - full suite including adversarial benchmarks')

# ---- D2 counts ----
def majors_bactrian(f):
    # "[mmtk] GCs: N (full: M), ..." -- full-flagged collections; cycles are
    # additional in the sliced regime (see presentation notes)
    for line in open(f, errors='replace'):
        if 'GCs:' in line:
            import re; m=re.search(r'full:\s*(\d+)',line); return int(m.group(1)) if m else None
def majors_vanilla(f):
    # v=0x400 prints a Gc.stat-style dump at exit; major_collections is the count
    for line in open(f, errors='replace'):
        if line.startswith('major_collections:'):
            return int(line.split(':')[1]) or None
vb=(R/'v.bt.verbose'); db=(R/'d2m.bt.verbose')
if vb.exists() and db.exists():
    vn, dn = majors_vanilla(vb), majors_bactrian(db)
    if vn and dn:
        fig,ax=plt.subplots(figsize=(6.4,4.6),dpi=150); fig.patch.set_facecolor(SURFACE); frame(ax)
        for x,v,c,l in [(0,dn,ORANGE,'Bactrian (2 MB nursery)'),(1,vn,AQUA,'Vanilla (o=500)')]:
            bar(ax,x,v,c,0.5); ax.text(x,v+0.6,str(v),ha='center',fontsize=12,color=TEXT2)
        ax.set_xticks([0,1]); ax.set_xticklabels(['Bactrian (2 MB)','Vanilla (o=500)'],fontsize=10,color=TEXT1)
        ax.set_ylabel('major collections per run',fontsize=10,color=TEXT1)
        ax.set_ylim(0,max(vn,dn)*1.15); ax.set_xlim(-0.6,1.6)
        ax.set_title('D2 - major collections, binarytrees',fontsize=12,color=TEXT1,loc='left',pad=12,fontweight='bold')
        plt.tight_layout(); plt.savefig(OUT/'d2_count.png',facecolor=SURFACE); plt.close()

# ---- D3 cumulative curves ----
def curve(f):
    xs=[0.0]; ys=[0.0]; c=0.0
    for line in open(f):
        j=json.loads(line)
        if j.get('kind')!='pause': continue
        c+=j['dur']; xs.append(j['at']); ys.append(c*1000)
    return xs,ys
streams=[('ddef.binarytrees.pause.ndjson',ORANGE,'Bactrian (default)'),
         ('v.binarytrees.pause.ndjson',AQUA,'Vanilla')]
have=[(R/f,c,l) for f,c,l in streams if (R/f).exists()]
if have:
    fig,ax=plt.subplots(figsize=(8.0,4.8),dpi=150); fig.patch.set_facecolor(SURFACE); frame(ax)
    for f,c,l in have:
        xs,ys=curve(f); ax.plot(xs,ys,color=c,linewidth=2.4,label=l)
    ax.set_xlabel('wall time, s',fontsize=10,color=TEXT1)
    ax.set_ylabel('cumulative stop-the-world time, ms',fontsize=10,color=TEXT1)
    ax.legend(loc='upper left',frameon=False,fontsize=10,labelcolor=TEXT1)
    ax.set_title('GC time over the run, binarytrees',fontsize=12,color=TEXT1,loc='left',pad=12,fontweight='bold')
    plt.tight_layout(); plt.savefig(OUT/'d3_curve.png',facecolor=SURFACE); plt.close()

# ---- D4 RSS ----
rows=[(b, rss('v',b), rss('d',b)) for b in ['weak_memo','matrix_multiplication','spectralnorm','kb','LU_decomposition','binarytrees']]
rows=[r for r in rows if r[1] and r[2]]
if rows:
    fig,ax=plt.subplots(figsize=(9.0,5.0),dpi=150); fig.patch.set_facecolor(SURFACE); frame(ax)
    w=0.36; gap=0.02; top=max(max(v,d) for _,v,d in rows)
    for i,(b,v,d) in enumerate(rows):
        for x,val,c in [(i-w/2-gap,v,AQUA),(i+w/2+gap,d,ORANGE)]:
            bar(ax,x,val,c,w); ax.text(x,val+top*0.02,f'{val:.0f}',ha='center',fontsize=9,color=TEXT2)
    ax.set_xticks(range(len(rows))); ax.set_xticklabels([SHORT[b] for b,_,_ in rows],fontsize=9,color=TEXT1)
    ax.set_ylabel('peak RSS, MB',fontsize=10,color=TEXT1); ax.set_ylim(0,top*1.15)
    ax.set_xlim(-0.85,len(rows)-0.15)
    ax.legend(handles=[mpatches.Patch(color=AQUA,label='Vanilla (o=500)'),
                       mpatches.Patch(color=ORANGE,label='Bactrian (192 MB fixed heap)')],
              loc='upper left',frameon=False,fontsize=9.5,labelcolor=TEXT1)
    ax.set_title('D4 - footprint: peak memory',fontsize=12,color=TEXT1,loc='left',pad=12,fontweight='bold')
    plt.tight_layout(); plt.savefig(OUT/'d4_rss.png',facecolor=SURFACE); plt.close()

# ---- D5 scatter ----
def d5read(bench):
    out={'v':[], 'd':[]}
    for f in R.glob(f'v5.{bench}.*.rss'):
        tag=f.name.split('.')[2]
        stats=[R/f'v5.{bench}.{tag}.r{r}.stat' for r in (1,2,3)]
        walls=[R/f'v5.{bench}.{tag}.r{r}.wall' for r in (1,2,3)]
        if all(s.exists() for s in stats):
            y=statistics.median(ev(s,'cycles') for s in stats)/1e9
        elif all(w.exists() for w in walls):
            y=statistics.median(float(open(w).read().split()[-1]) for w in walls)
        else: continue
        out['v'].append((int(open(f).read().split()[-1])/1024, y))
    for f in R.glob(f'd5.{bench}.*.rss'):
        tag=f.name.split('.')[2]
        stats=[R/f'd5.{bench}.{tag}.r{r}.stat' for r in (1,2,3)]
        walls=[R/f'd5.{bench}.{tag}.r{r}.wall' for r in (1,2,3)]
        if all(s.exists() for s in stats):
            y=statistics.median(ev(s,'cycles') for s in stats)/1e9
        elif all(w.exists() for w in walls):
            y=statistics.median(float(open(w).read().split()[-1]) for w in walls)
        else: continue
        out['d'].append((int(open(f).read().split()[-1])/1024, y))
    return out
panels=[b for b in ('kb','binarytrees') if list(R.glob(f'v5.{b}.*.rss'))]
if panels:
    fig,axes=plt.subplots(1,len(panels),figsize=(5.8*len(panels),5.2),dpi=150,squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax,b in zip(axes[0],panels):
        frame(ax); ax.xaxis.grid(True,color=GRID,linewidth=0.8)
        data=d5read(b)
        # drop degenerate cells (documented knob-interaction corner)
        ys=[y for _,y in data['d']] or [1]
        med=statistics.median(ys)
        dd=[(x,y) for x,y in data['d'] if y<=5*med]
        ax.scatter([p[0] for p in data['v']],[p[1] for p in data['v']],s=48,color=AQUA,alpha=0.85,linewidths=0)
        ax.scatter([p[0] for p in dd],[p[1] for p in dd],s=48,color=ORANGE,alpha=0.85,linewidths=0)
        ax.set_title(b,fontsize=10.5,color=TEXT1,loc='left',pad=8)
        ax.set_xlabel('peak RSS, MB',fontsize=9.5,color=TEXT1)
        ax.set_ylabel('cost (cycles G or wall s)',fontsize=9.5,color=TEXT1)
    axes[0][-1].legend(handles=[mpatches.Patch(color=ORANGE,label='Bactrian (all configurations)'),
                                mpatches.Patch(color=AQUA,label='Vanilla (s x o grid)')],
                       loc='upper right',frameon=False,fontsize=9,labelcolor=TEXT1)
    fig.suptitle('D5 - space-time: every configuration of each collector',
                 fontsize=12.5,color=TEXT1,x=0.012,ha='left',fontweight='bold')
    plt.tight_layout(rect=(0,0.02,1,0.92)); plt.savefig(OUT/'d5_scatter.png',facecolor=SURFACE); plt.close()

print(f'charts written to {OUT}')
