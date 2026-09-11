#!/usr/bin/env bash
# Macro benches before/after the slicing gate: default rungs, default (dynamic) heap, 1 GC worker.
set -u; R=$HOME/shape/macro/gate-results; mkdir -p "$R"; SA="setarch x86_64 -R"; PIN="taskset -c 0-13"
declare -A ARGS=( [decompress/test_decompress]="1 268435456" [eio/eio_conc_bench]="9000" [liq-video-frames/liq_video_frames]="15000 3840 2160"
  [sedlex/sedlex_bench]="6000000" [yojson/ydump_repeat]="1 6000000" [zarith/zarith_pi]="38000" )
for side in gate-before gate-after; do for k in decompress/test_decompress eio/eio_conc_bench liq-video-frames/liq_video_frames sedlex/sedlex_bench yojson/ydump_repeat zarith/zarith_pi; do
  d=${k%/*}; exe=${k##*/}; dir=$HOME/shape/macro/$side/$d; [ -x "$dir/$exe.exe" ] || { echo "MISSING $side/$k"; continue; }; cd "$dir"
  ws=""; for rep in 1 2 3; do w=$(env MMTK_PLAN=Bactrian MMTK_THREADS=1 timeout 1500 /usr/bin/time -f "%e %M" $PIN $SA "./$exe.exe" ${ARGS[$k]} 2>&1 >/dev/null | tail -1); ws="$ws|$w"; done
  env MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_VERBOSE=1 MMTK_PAUSE_LOG="$R/$side.$exe.pause.ndjson" timeout 1500 $PIN $SA "./$exe.exe" ${ARGS[$k]} >/dev/null 2>"$R/$side.$exe.verbose"
  python3 - "$side" "$exe" "$ws" "$R" <<PY
import json,sys,re
side,exe,ws,R=sys.argv[1:5]; rows=[w.split() for w in ws.strip("|").split("|") if w.strip()]
walls=sorted(float(r[0]) for r in rows if len(r)==2); rss=max(int(r[1]) for r in rows if len(r)==2)//1024
try:
    p=[json.loads(l) for l in open(f"{R}/{side}.{exe}.pause.ndjson") if l.startswith("{")]; p=[x for x in p if x.get("kind")=="pause"]
    d=[x["dur"]*1000 for x in p]; full=[x for x in p if x.get("full")]; mx=max(d) if d else 0; n=len(p); nf=len(full)
except Exception: mx=n=nf=-1
gc=[l.strip() for l in open(f"{R}/{side}.{exe}.verbose",errors="replace") if "GCs:" in l]
print(f"{side} {exe}: wall_med={walls[len(walls)//2] if walls else -1:.2f}s (n={len(walls)}) rss={rss}MB pauses={n} fulls={nf} max_pause={mx:.0f}ms | {gc[0] if gc else '?'}")
PY
done; done; echo MACRO-GATE-DONE
