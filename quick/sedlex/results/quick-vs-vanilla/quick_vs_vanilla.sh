#!/usr/bin/env bash
# 11-bench quick panel (CLBG-style seq + kb + 3 adversarial), vanilla vs Bactrian gate vs Bactrian v5.
# Laptop P-cores 0-5, setarch -R, dynamic heap, 1 GC worker. Per side/bench: golden, wall x3 (+RSS), GC counts, max pause.
set -u; Q=/home/r41k0u/ocaml/mmtk_for_ocaml/shape-bench/quick; R=$Q/sedlex/results/quick-vs-vanilla; mkdir -p $R
SA="setarch x86_64 -R"; PIN="taskset -c 0-5"; OLLY=/home/r41k0u/.opam/vanilla-5.5.0/bin/olly
declare -A SZ=( [binarytrees]=20 [nbody]=20000000 [fannkuchredux]=11 [spectralnorm]=3000 [mandelbrot]=4000 [matrix_multiplication]=768 [LU_decomposition]=900 [kb]=50 [mature_mutation]=8 [weak_memo]=800 [fragmed]=150 )
PANEL="${BENCHES:-nbody fannkuchredux mandelbrot spectralnorm LU_decomposition matrix_multiplication binarytrees kb weak_memo mature_mutation fragmed}"
cd $Q
for side in ${SIDES:-vanilla gate-after gate-v5}; do
  case $side in vanilla) BIN=build_vanilla; ENV="";; gate-after) BIN=build-gate-after; ENV="MMTK_PLAN=Bactrian MMTK_THREADS=1";; gate-v5) BIN=build-gate-v5; ENV="MMTK_PLAN=Bactrian MMTK_THREADS=1";; esac
  for b in $PANEL; do
    exe=./$BIN/$b.native; [ -x $exe ] || { echo "MISSING $side/$b"; continue; }
    env $ENV $PIN $SA $exe ${SZ[$b]} 2>/dev/null | cmp -s - golden/$b.out && g=OK || g=MISMATCH
    ws=""; for r in 1 2 3; do w=$(env $ENV /usr/bin/time -f "%e %M" $PIN $SA $exe ${SZ[$b]} 2>&1 >/dev/null | tail -1); ws="$ws|$w"; done
    if [ $side = vanilla ]; then
      OCAMLRUNPARAM=v=0x400 $PIN $SA $exe ${SZ[$b]} >/dev/null 2>$R/$side.$b.v400
      $PIN $SA $OLLY gc-stats "$exe ${SZ[$b]}" >$R/$side.$b.ollystats 2>&1
      python3 - $side $b "$ws" $R $g <<PY
import re,sys
side,b,ws,R,g=sys.argv[1:6]; rows=[w.split() for w in ws.strip("|").split("|") if w.strip()]
walls=sorted(float(r[0]) for r in rows if len(r)==2); rss=max(int(r[1]) for r in rows if len(r)==2)//1024
v=open(f"{R}/{side}.{b}.v400",errors="replace").read(); o=open(f"{R}/{side}.{b}.ollystats",errors="replace").read()
def gi(k):
    m=re.search(k+r":\s*(\d+)",v); return int(m.group(1)) if m else -1
gct=re.search(r"GC time \(s\):\s*([0-9.]+)",o); mx=re.search(r"max \(ms\):\s*([0-9.]+)",o)
print(f"{side} {b}: golden={g} wall_med={walls[len(walls)//2]:.3f}s (n={len(walls)}) rss={rss}MB minors={gi('minor_collections')} majors={gi('major_collections')} promoted_words={gi('promoted_words')} gc_time={gct.group(1) if gct else '?'}s max_pause={mx.group(1) if mx else '?'}ms")
PY
    else
      env $ENV MMTK_VERBOSE=1 MMTK_PAUSE_LOG=$R/$side.$b.pause.ndjson $PIN $SA $exe ${SZ[$b]} >/dev/null 2>$R/$side.$b.verbose
      python3 - $side $b "$ws" $R $g <<PY
import json,sys
side,b,ws,R,g=sys.argv[1:6]; rows=[w.split() for w in ws.strip("|").split("|") if w.strip()]
walls=sorted(float(r[0]) for r in rows if len(r)==2); rss=max(int(r[1]) for r in rows if len(r)==2)//1024
p=[json.loads(l) for l in open(f"{R}/{side}.{b}.pause.ndjson") if l.startswith("{")]; p=[x for x in p if x.get("kind")=="pause"]
d=[x["dur"]*1000 for x in p]; nf=sum(1 for x in p if x.get("full")); mx=max(d) if d else 0
gc=[l.strip() for l in open(f"{R}/{side}.{b}.verbose",errors="replace") if "GCs:" in l]
print(f"{side} {b}: golden={g} wall_med={walls[len(walls)//2]:.3f}s (n={len(walls)}) rss={rss}MB pauses={len(p)} fulls={nf} max_pause={mx:.1f}ms | {gc[0] if gc else '?'}")
PY
    fi
  done
done; echo QUICK-VS-VANILLA-DONE
