#!/bin/bash
# NURSERY SWEEP (round 31): MMTK_NURSERY Fixed {2,4,8,16}MB on the settled
# default config (band=immix). D1 all 11 benches x2 reps + RSS; D3 pause
# streams (bt kb matmut); D4 RSS streams (bt kb sp matmut). Vanilla D1
# reference comes from wcomp8 (identical binaries/config).
set -u
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/local/bin:$PATH"
OUT=$HOME/shape/nsweep; mkdir -p $OUT/streams
Q=$HOME/shape/shape-bench/quick; cd $Q
SA="setarch x86_64 -R"
log(){ echo "[$(date +%H:%M:%S)] $*" >> $OUT/RUNLOG; }
log "commit: $(cd ~/shape/ocaml-mmtk && git log --oneline -1)"
declare -A SZ=( [binarytrees]=20 [nbody]=20000000 [fannkuchredux]=11
  [spectralnorm]=3000 [mandelbrot]=4000 [matrix_multiplication]=768
  [LU_decomposition]=900 [kb]=50 [mature_mutation]=8 [weak_memo]=800 [fragmed]=150 )
ALL="binarytrees nbody fannkuchredux spectralnorm mandelbrot matrix_multiplication LU_decomposition kb mature_mutation weak_memo fragmed"

for n in 2 4 8 16; do
  NB=$((n*1048576))
  B="MMTK_PLAN=Bactrian MMTK_HEAP_SIZE_MB=192 MMTK_THREADS=1 MMTK_NURSERY=Fixed:$NB"
  log "== D1 n$n"
  for b in $ALL; do
    for r in 1 2; do
      env $B perf stat -e cycles,duration_time -x, -o $OUT/n$n.$b.r$r.stat -- taskset -c 0-13 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2>/dev/null
    done
    env $B /usr/bin/time -f %M taskset -c 0-13 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2> $OUT/n$n.$b.rss
  done
  log "== D3 n$n"
  for b in binarytrees kb mature_mutation; do
    env $B MMTK_PAUSE_LOG=$OUT/streams/n$n.$b.pause.ndjson MMTK_VERBOSE=1 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2>$OUT/streams/n$n.$b.verbose
  done
  log "== D4 n$n"
  for b in binarytrees kb spectralnorm mature_mutation; do
    taskset -c 0-13 env MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_NURSERY=Fixed:$NB python3 lib/rss_sampler.py --out $OUT/streams/n$n.$b.rss.ndjson --interval-ms 10 -- ./build/mmtk/$b.native ${SZ[$b]} >/dev/null 2>&1
  done
  log "done n$n"
done
log "=== NSWEEP COMPLETE"
touch $OUT/DONE
