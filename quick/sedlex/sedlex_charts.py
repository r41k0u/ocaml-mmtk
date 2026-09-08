#!/usr/bin/env python3
"""sedlex_charts.py <results-dir> <out-dir> — charts for the sedlex investigation.
Reads the reproducer's text outputs; skips any chart whose inputs are missing."""
import glob, math, os, re, sys, collections
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
R, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
SURFACE='#fcfcfb'; TEXT1='#0b0b0b'; TEXT2='#52514e'; GRID='#e8e7e4'
ORANGE='#eb6834'; AQUA='#1baf7a'; MUTED='#e8a091'; SLATE='#6b7280'
def frame(ax):
    ax.set_facecolor(SURFACE); ax.yaxis.grid(True,color=GRID,linewidth=0.8); ax.set_axisbelow(True)
    for s in ('top','right','left'): ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(GRID); ax.tick_params(colors=TEXT2,length=0)
def fig(w=8,h=4.6): f,ax=plt.subplots(figsize=(w,h),dpi=150); f.patch.set_facecolor(SURFACE); frame(ax); return f,ax
def title(ax,t): ax.set_title(t,fontsize=12,color=TEXT1,loc='left',pad=12,fontweight='bold')
def save(f,name): plt.tight_layout(); f.savefig(os.path.join(OUT,name),facecolor=SURFACE); plt.close(f); print('wrote',name)
def rd(name):
    p=os.path.join(R,name); return open(p).read().splitlines() if os.path.exists(p) else []
num=lambda pat,s,default=None: (float(re.search(pat,s).group(1)) if re.search(pat,s) else default)

# ---- 1. nursery sweep: long-lived (sedlex) vs short-lived (binarytrees) ----
def series(lines, key):
    out=collections.defaultdict(list)
    for l in lines:
        mb=num(r'nursery=(\d+)MB',l); w=num(r'wall=([\d.]+)s',l)
        if mb is None or w is None: continue
        if l.startswith('bactrian') and 'backstop=off' in l: out['Bactrian, backstop off'].append((mb,w))
        elif l.startswith('bactrian'): out['Bactrian (default)'].append((mb,w))
        elif l.startswith('vanilla'): out['Vanilla'].append((mb,w))
    return {k:sorted(v) for k,v in out.items()}
sed=series(rd('nursery_sweep.txt'),'sedlex'); bt=series(rd('bt_control.txt'),'bt')
if sed or bt:
    # one axis, wall time in seconds on a log scale so both workloads keep their true shape:
    # equal ratios are equal vertical distances. colour = runtime, line style = workload.
    f,ax=fig(9.5,5.2); title(ax,'Nursery-size sensitivity: wall time vs nursery size')
    style={('sedlex','Bactrian (default)'):(ORANGE,'-','sedlex: Bactrian (default)'),
           ('sedlex','Bactrian, backstop off'):(MUTED,'-','sedlex: Bactrian, backstop off'),
           ('sedlex','Vanilla'):(AQUA,'-','sedlex: Vanilla'),
           ('bt','Bactrian (default)'):(ORANGE,(0,(4,2)),'binarytrees: Bactrian'),
           ('bt','Vanilla'):(AQUA,(0,(4,2)),'binarytrees: Vanilla')}
    ends=[]
    for wl,data in (('sedlex',sed),('bt',bt)):
        for lbl,pts in data.items():
            if (wl,lbl) not in style or not pts: continue
            c,ls,name=style[(wl,lbl)]
            xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
            ax.plot(xs,ys,color=c,linestyle=ls,linewidth=2.2,marker='o',markersize=5.5)
            ends.append((xs[-1],ys[-1],c,name,f'{pts[-1][1]:.1f} s'))
    # direct labels at line ends, nudged apart if they collide
    ends.sort(key=lambda e:e[1]); last=None
    for x,y,c,name,abs_ in ends:
        yy=y if last is None or y/last>1.12 else last*1.12; last=yy
        ax.text(x*1.15,yy,f'{name}  ({abs_} at {x:.0f} MB)',fontsize=8.6,color=c,va='center')
    ax.set_xscale('log',base=2); ax.set_xlim(1.6,2**8*6.5); ax.set_yscale('log'); ax.set_ylim(2,70)
    import matplotlib.ticker as mt; ax.yaxis.set_major_locator(mt.FixedLocator([2,3,5,7,10,20,30,50])); ax.yaxis.set_major_formatter(mt.FormatStrFormatter('%g')); ax.yaxis.set_minor_locator(mt.NullLocator())
    ax.set_xlabel('nursery size, MB (log2)',fontsize=9.5,color=TEXT1); ax.set_ylabel('wall time, s (log)',fontsize=9.5,color=TEXT1)
    ax.text(0.01,0.03,'solid = sedlex n=1M (long-lived), dashed = binarytrees n=20 (short-lived); orange = Bactrian, green = Vanilla',transform=ax.transAxes,fontsize=8.5,color=TEXT2)
    save(f,'nursery_sweep_log.png')

# ---- 2. pause-class split at n=1M ----
ps={}
for l in rd('pause_split.txt'):
    if l.startswith('#') or not l.strip(): continue
    k=l.split()[0]; ps[k]={kv.split('=')[0]:float(kv.split('=')[1]) for kv in l.split()[1:]}
if ps:
    f,ax=fig(7.5,4.6); title(ax,'Where the time goes, sedlex n=1M (seconds)')
    rows=[('Vanilla',ps.get('vanilla',{}),[('minor','promotion (minor)'),('major','major slices'),('mutator','mutator')]),
          ('Bactrian',ps.get('bactrian',{}),[('nursery','promotion (nursery)'),('full','full re-marks'),('mutator','mutator')]),
          ('Bactrian,\nbackstop off',ps.get('bactrian_backstop_off',{}),[('nursery','promotion (nursery)'),('full','full re-marks'),('mutator','mutator')])]
    cols=[AQUA,SLATE,'#c9c7c2']; shades={'Vanilla':[AQUA,'#7fd4b3','#c9c7c2'],'Bactrian':[ORANGE,'#b04a24','#c9c7c2'],'Bactrian,\nbackstop off':[MUTED,'#d08a6a','#c9c7c2']}
    for i,(name,d,parts) in enumerate(rows):
        b=0
        for (k,lbl),c in zip(parts,shades[name]):
            v=d.get(k,0); ax.add_patch(FancyBboxPatch((i-0.3,b),0.6,v,boxstyle='round,pad=0,rounding_size=0.01',linewidth=0,facecolor=c))
            if v>3.5: ax.text(i,b+v/2,f'{lbl}\n{v:.1f}',ha='center',va='center',fontsize=8,color='white' if c not in ('#c9c7c2','#7fd4b3') else TEXT1)
            elif v>0.3: ax.text(i+0.33,b+v/2,f'{lbl} {v:.2f}',ha='left',va='center',fontsize=7.5,color=TEXT2)
            b+=v
        ax.text(i,b+0.6,f'{b:.1f} s',ha='center',fontsize=9.5,color=TEXT2)
    ax.set_xticks(range(len(rows))); ax.set_xticklabels([r[0] for r in rows],fontsize=9.5,color=TEXT1); ax.set_xlim(-0.6,len(rows)-0.4); ax.set_ylim(0,48)
    ax.set_ylabel('seconds',fontsize=9.5,color=TEXT1); save(f,'pause_split.png')

# ---- 3. remset growth (probed build) ----
logs=sorted(glob.glob(os.path.join(R,'remset.*.*.log')))
if logs:
    f,axes=plt.subplots(1,2,figsize=(11,4.6),dpi=150); f.patch.set_facecolor(SURFACE)
    ax=axes[0]; frame(ax); title(ax,'Per nursery GC (16 MB): promoted vs remset')
    cum={}
    for p in logs:
        m=re.search(r'remset\.(\d+)\.(\d+)\.log',p); n,mb=int(m.group(1)),int(m.group(2))
        rem=[]; prom=[]; tot=None
        for l in open(p):
            if not l.startswith('[probe]') or 'kind=Nursery' not in l: continue
            rem.append(num(r' modbuf_objs=(\d+)',l)+num(r' region_entries=(\d+)',l))
            prom.append(max(num(r' copied=(\d+)',l), num(r' scanned=(\d+)',l)))
            cumtail=l.split('| cum ',1)[1] if '| cum ' in l else ''
            tot=(num(r'modbuf=(\d+)',cumtail),num(r'region=(\d+)',cumtail),num(r'satb=(\d+)',cumtail),num(r'copied=(\d+)',cumtail),num(r'scanned=(\d+)',cumtail))
        cum[(n,mb)]=tot
        if mb==16 and prom:
            c={500000:MUTED,1000000:ORANGE,2000000:'#b04a24'}.get(n,SLATE)
            ax.plot(range(len(prom)),prom,linewidth=1.4,color=c,label=f'promoted, n={n//1000}K')
            ax.plot(range(len(rem)),rem,linewidth=1.4,color=SLATE,linestyle='--',label='remset entries' if n==1000000 else None)
    ax.set_yscale('symlog',linthresh=10); ax.set_ylim(0,3e6)
    ax.set_xlabel('nursery GC index',fontsize=9.5,color=TEXT1); ax.set_ylabel('objects (symlog)',fontsize=9.5,color=TEXT1); ax.legend(frameon=False,fontsize=8.5,labelcolor=TEXT1,loc='center right')
    ax=axes[1]; frame(ax); title(ax,'Whole run: remset vs promoted')
    ns=sorted({k[0] for k in cum if k[1]==16})
    for i,n in enumerate(ns):
        t=cum.get((n,16))
        if not t: continue
        rem=(t[0] or 0)+(t[1] or 0); cp=max(t[3] or 0, t[4] or 0)
        ax.bar(i-0.17,max(rem,1),width=0.3,color=SLATE,linewidth=0); ax.text(i-0.17,max(rem,1)*1.25,f'{rem:,.0f}',ha='center',va='bottom',fontsize=8,color=TEXT2)
        ax.bar(i+0.17,max(cp,1),width=0.3,color=ORANGE,linewidth=0); ax.text(i+0.17,cp*1.25,f'{cp/1e6:.1f}M',ha='center',va='bottom',fontsize=8,color=TEXT2)
    ax.set_yscale('log'); ax.set_ylim(1,1e9); ax.set_xlim(-0.6,len(ns)-0.4)
    ax.set_xticks(range(len(ns))); ax.set_xticklabels([f'n={n//1000}K' for n in ns],fontsize=9.5,color=TEXT1); ax.set_ylabel('count (log)',fontsize=9.5,color=TEXT1)
    ax.text(0.02,0.97,'grey = remset entries (modbuf + region), orange = objects promoted',transform=ax.transAxes,fontsize=8.5,color=TEXT2,va='top')
    save(f,'remset_growth.png')

# ---- 4. coloring: Δwall vs injected delay per stage → invocation counts ----
col=[]
# precedence: a stage's rows come from the first file (in this order) that has them
PRIO=['coloring2.txt','coloring_objcopy.txt','coloring.txt']
files=[f for f in PRIO if os.path.exists(os.path.join(R,f))]+sorted(f for f in map(os.path.basename,glob.glob(os.path.join(R,'coloring*.txt'))) if f not in PRIO)
for fn in files:
    for l in open(os.path.join(R,fn)).read().splitlines():
        if l and not l.startswith('stage'): col.append((fn,)+tuple(l.split()))
if col:
    base={}; pts=collections.defaultdict(list); src={}
    for fn,cfg,st,ns,w in col:
        w=float(w)
        if st=='none': base[(fn,cfg)]=w; continue
        if (cfg,st) in src and src[(cfg,st)]!=fn: continue
        src[(cfg,st)]=fn; pts[(cfg,st)].append((float(ns),w,fn))
    def dwall(cfg,st,v): return [(x, w-base.get((fn,cfg), base.get(('coloring.txt',cfg),0))) for x,w,fn in v]
    f,axes=plt.subplots(1,2,figsize=(11,4.8),dpi=150); f.patch.set_facecolor(SURFACE)
    counts={}
    for ax,cfg in zip(axes,['default','off']):
        frame(ax); title(ax,f'Stage coloring, sedlex n=1M — backstop {cfg}')
        for (c,st),v in sorted(pts.items()):
            if c!=cfg: continue
            d=sorted(dwall(cfg,st,v)); xs=[p[0] for p in d]; dy=[p[1] for p in d]
            # slope (s per ns) → invocations = slope * 1e9
            if len(xs)>=2:
                sx=sum(xs); sy=sum(dy); sxx=sum(x*x for x in xs); sxy=sum(x*y for x,y in zip(xs,dy)); n=len(xs)
                slope=(n*sxy-sx*sy)/(n*sxx-sx*sx) if n*sxx-sx*sx else 0
            else: slope=dy[0]/xs[0] if xs[0] else 0
            N=slope*1e9; noise = slope <= 0 or abs(slope*max(xs)) < 1.0   # non-positive, or slope-implied shift at the largest delay < 1 s: within run-to-run noise
            counts[(cfg,st)]=max(N,0.0) if not noise else 0.0
            ax.plot([x/1e3 for x in xs],dy,marker='o',markersize=5,linewidth=1.6,label=f'{st}: N≈{N:,.0f}' if not noise else f'{st}: ≈0 (within noise)')
        ax.set_xscale('log'); ax.set_xlabel('injected delay per invocation, µs',fontsize=9.5,color=TEXT1); ax.set_ylabel('Δ wall vs no injection, s',fontsize=9.5,color=TEXT1)
        ax.legend(frameon=False,fontsize=8,labelcolor=TEXT1)
    save(f,'coloring.png')
    # natural per-invocation cost = pause-class total / N (pause_split.txt: nursery/full totals per config)
    tot={'default':ps.get('bactrian',{}),'off':ps.get('bactrian_backstop_off',{})} if ps else {}
    pool={'nursery_pause':'nursery','object_copy':'nursery','scan_object':'nursery','modbuf_object':'nursery','full_pause':'full','cycle_pause':'full','mark_quantum':'full','sweep_quantum':'full'}
    with open(os.path.join(OUT,'coloring_counts.txt'),'w') as fh:
        fh.write('config stage N_from_slope pool_total_s natural_cost_per_invocation\n')
        for (cfg,st),n in sorted(counts.items()):
            T=tot.get(cfg,{}).get(pool.get(st,''),None)
            cost=(f'{T/n*1e9:,.0f} ns' if n>1e5 else f'{T/n*1e3:,.1f} ms') if (T and n>0.5) else 'n/a'
            fh.write(f'{cfg} {st} N={n:,.0f} pool={T if T is not None else "?"}s cost={cost}\n')
    print(open(os.path.join(OUT,'coloring_counts.txt')).read())
# ---- 5. direct per-stage cycles (rdtsc inside the probes; no wall-time attribution) ----
cyc=sorted(glob.glob(os.path.join(R,'cycles.*.*.txt')))
if cyc:
    stages=['object_copy','scan_object','nursery_pause','full_pause','cycle_pause','modbuf_object','mark_quantum','sweep_quantum']
    data={}
    for fn in cyc:
        m=re.search(r'cycles\.(\w+)\.(\d+)\.txt',fn); cfg,n=m.group(1),int(m.group(2))
        line=[l for l in open(fn) if l.startswith('[cycles]')]
        if not line: continue
        line=line[-1]; hz=num(r'tsc_hz=([\d.]+)',line); ovh=num(r'timer_overhead_ticks=([\d.]+)',line)
        st={}
        for part in line.split('|')[1:]:
            mm=re.match(r'\s*(\w+): n=(\d+) ticks=(\d+) per_call=([\d.\-]+) corrected_per_call=([\d.\-]+) secs=([\d.\-]+)',part)
            if mm: st[mm.group(1)]=dict(n=int(mm.group(2)),ticks=int(mm.group(3)),per=float(mm.group(4)),cper=float(mm.group(5)),secs=float(mm.group(6)))
        wall=None
        for l in open(fn):
            w=num(r'wall=([\d.]+)',l)
            if w: wall=w
        data[(cfg,n)]=dict(hz=hz,ovh=ovh,st=st,wall=wall)
    # chart: per-stage seconds (direct), n=1M, default vs off; pause-log pools as hollow markers for cross-check
    keys=[k for k in [('default',1000000),('off',1000000)] if k in data]
    if keys:
        f,ax=fig(9.5,4.8); title(ax,'Direct per-stage time from rdtsc inside the probes (sedlex n=1M)')
        w=0.38
        for j,k in enumerate(keys):
            d=data[k]['st']; col=ORANGE if k[0]=='default' else MUTED
            for i,stg in enumerate(stages):
                v=d.get(stg,{}).get('secs',0.0)
                ax.bar(i+(j-0.5)*w,max(v,0),width=w*0.92,color=col,linewidth=0)
                if v>0.3: ax.text(i+(j-0.5)*w,v+0.4,f'{v:.1f}',ha='center',fontsize=7.5,color=TEXT2)
        # cross-check markers from the pause log (pause_split.txt)
        pools={'default':ps.get('bactrian',{}),'off':ps.get('bactrian_backstop_off',{})} if ps else {}
        for j,k in enumerate(keys):
            pl=pools.get(k[0],{})
            for stg,key in (('nursery_pause','nursery'),('full_pause','full')):
                if key in pl: ax.plot([stages.index(stg)+(j-0.5)*w],[pl[key]],marker='D',markersize=6,markerfacecolor='none',markeredgecolor=TEXT1,markeredgewidth=1.2,linestyle='none')
        ax.set_ylim(0,max([v.get('secs',0) for k in keys for v in data[k]['st'].values()]+[1])*1.28)
        ax.set_xticks(range(len(stages))); ax.set_xticklabels(stages,fontsize=8.5,color=TEXT1,rotation=20,ha='right')
        ax.set_ylabel('seconds (TSC ticks ÷ TSC rate, timer overhead subtracted)',fontsize=9,color=TEXT1)
        ax.text(0.01,0.97,'orange = backstop default, pink = backstop off; hollow diamonds = pause-log class totals (independent cross-check)',transform=ax.transAxes,fontsize=8.5,color=TEXT2,va='top')
        save(f,'stage_cycles.png')
    with open(os.path.join(OUT,'stage_cycles.txt'),'w') as fh:
        for k,d in sorted(data.items()):
            fh.write(f"# {k[0]} n={k[1]} wall={d['wall']} tsc_hz={d['hz']:.0f} timer_overhead_ticks={d['ovh']:.1f}\n")
            for stg in stages:
                if stg in d['st']:
                    x=d['st'][stg]; fh.write(f"{k[0]} {k[1]} {stg} n={x['n']} ticks/call={x['per']:.0f} corrected={x['cper']:.0f} secs={x['secs']:.3f}\n")
    print(open(os.path.join(OUT,'stage_cycles.txt')).read())
print('done')
