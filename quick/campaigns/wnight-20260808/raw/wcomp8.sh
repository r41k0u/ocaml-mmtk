#!/bin/bash
# V4 COMPREHENSIVE: 11-bench D1 both sides + oldify-on variant; D2/D3/D4
# streams (bt kb LU sp + mature_mutation); attribution; pareto kb+bt.
set -u
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/local/bin:$PATH"
OUT=$HOME/shape/wcomp8; mkdir -p $OUT/streams
Q=$HOME/shape/shape-bench/quick; cd $Q
GCP=$HOME/shape/results/20260807/bin/gcpauses
SA="setarch x86_64 -R"
B="MMTK_PLAN=Bactrian MMTK_HEAP_SIZE_MB=192 MMTK_THREADS=1"
log(){ echo "[$(date +%H:%M:%S)] $*" >> $OUT/RUNLOG; }
log "commit: $(cd ~/shape/ocaml-mmtk && git log --oneline -1)"
declare -A SZ=( [binarytrees]=20 [nbody]=20000000 [fannkuchredux]=11
  [spectralnorm]=3000 [mandelbrot]=4000 [matrix_multiplication]=768
  [LU_decomposition]=900 [kb]=50 [mature_mutation]=8 [weak_memo]=800 [fragmed]=150 )
ALL="binarytrees nbody fannkuchredux spectralnorm mandelbrot matrix_multiplication LU_decomposition kb mature_mutation weak_memo fragmed"

log "== D1 panel (v, d, d+oldify)"
for b in $ALL; do
  for r in 1 2 3; do
    env OCAMLRUNPARAM=o=500 perf stat -e cycles,instructions,duration_time -x, -o $OUT/v.$b.r$r.stat -- taskset -c 0-13 $SA ./build_vanilla/$b.native ${SZ[$b]} > /dev/null 2>/dev/null
    env $B perf stat -e cycles,instructions,duration_time -x, -o $OUT/d.$b.r$r.stat -- taskset -c 0-13 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2>/dev/null
    env $B MMTK_UP_OLDIFY=1 perf stat -e cycles,instructions,duration_time -x, -o $OUT/o.$b.r$r.stat -- taskset -c 0-13 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2>/dev/null
  done
  env OCAMLRUNPARAM=o=500 /usr/bin/time -f %M taskset -c 0-13 $SA ./build_vanilla/$b.native ${SZ[$b]} > /dev/null 2> $OUT/v.$b.rss
  env $B /usr/bin/time -f %M taskset -c 0-13 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2> $OUT/d.$b.rss
  log "D1 $b"
done

STREAMB="binarytrees kb LU_decomposition spectralnorm mature_mutation"
log "== D3 pause streams"
for b in $STREAMB; do
  PFX=$OUT/streams/v.$b; rm -rf $PFX.ring; mkdir -p $PFX.ring
  taskset -c 0-13 env OCAMLRUNPARAM=o=500 OCAML_RUNTIME_EVENTS_START=1 OCAML_RUNTIME_EVENTS_DIR=$PFX.ring \
    ./build_vanilla/$b.native ${SZ[$b]} >/dev/null 2>$PFX.stderr &
  TP=$!; $GCP $PFX.ring $TP $PFX.pause.ndjson 2>>$PFX.stderr; wait $TP; rm -rf $PFX.ring
  env $B MMTK_PAUSE_LOG=$OUT/streams/d.$b.pause.ndjson MMTK_VERBOSE=1 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2>$OUT/streams/d.$b.verbose
  env $B MMTK_NURSERY=Fixed:2097152 MMTK_PAUSE_LOG=$OUT/streams/dn2.$b.pause.ndjson MMTK_VERBOSE=1 $SA ./build/mmtk/$b.native ${SZ[$b]} > /dev/null 2>$OUT/streams/dn2.$b.verbose
  log "D3 $b"
done

log "== D2 probe streams (bt kb LU sp)"
for b in binarytrees kb LU_decomposition spectralnorm; do
  env OCAMLRUNPARAM=o=500 PROBE_OUT=$OUT/streams/v.$b.probe.ndjson taskset -c 0-13 $SA ./build_vanilla/$b.probe.native ${SZ[$b]} > /dev/null 2>>$OUT/probe.log || log "no v probe $b"
  env $B PROBE_OUT=$OUT/streams/d.$b.probe.ndjson taskset -c 0-13 $SA ./build/mmtk/$b.probe.native ${SZ[$b]} > /dev/null 2>>$OUT/probe.log || log "no d probe $b"
  log "D2 $b"
done

log "== D4 RSS streams"
for b in $STREAMB; do
  taskset -c 0-13 env OCAMLRUNPARAM=o=500 python3 lib/rss_sampler.py --out $OUT/streams/v.$b.rss.ndjson --interval-ms 10 -- ./build_vanilla/$b.native ${SZ[$b]} >/dev/null 2>&1
  taskset -c 0-13 env MMTK_PLAN=Bactrian MMTK_THREADS=1 python3 lib/rss_sampler.py --out $OUT/streams/d.$b.rss.ndjson --interval-ms 10 -- ./build/mmtk/$b.native ${SZ[$b]} >/dev/null 2>&1
  log "D4 $b"
done

log "== attribution (bt@n8, oldify on + off)"
for k in 0 1; do
  env $B MMTK_UP_OLDIFY=$k MMTK_NURSERY=Fixed:8388608 perf record -q -e cycles -F 2999 -o $OUT/attr.$k.data -- taskset -c 0-13 $SA ./build/mmtk/binarytrees.native 20 > /dev/null 2>/dev/null
  perf report -i $OUT/attr.$k.data --stdio --no-children --comm mmtk-gc-worker --percent-limit 0.05 2>/dev/null > $OUT/attr.$k.worker.txt
  env $B MMTK_UP_OLDIFY=$k MMTK_NURSERY=Fixed:8388608 MMTK_VERBOSE=1 $SA ./build/mmtk/binarytrees.native 20 > /dev/null 2>$OUT/attr.$k.verbose
  env $B MMTK_UP_OLDIFY=$k MMTK_NURSERY=Fixed:8388608 perf stat -e cycles -x, -o $OUT/attr.$k.whole -- taskset -c 0-13 $SA ./build/mmtk/binarytrees.native 20 > /dev/null 2>/dev/null
  perf report -i $OUT/attr.$k.data --stdio --no-children --comm mmtk-gc-worker --percent-limit 0 2>/dev/null | grep -E "^\s+[0-9]" | awk '{gsub(/%/,"",$1); s+=$1} END {print s}' > $OUT/attr.$k.wshare
done
log "== pareto refresh (kb bt)"
declare -A HEAPS=( [kb]="24 32 48 64" [binarytrees]="96 128 192 256" )
: > $OUT/pareto.ndjson
for b in kb binarytrees; do
  for h in ${HEAPS[$b]}; do
    for n in 2097152 8388608 16777216; do
      nm=$((n/1048576)); best_rss=99999999; best_wall=999999
      for r in 1 2; do
        out=$(env MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_HEAP_SIZE_MB=$h MMTK_NURSERY=Fixed:$n /usr/bin/time -f "%M %e" taskset -c 0-13 $SA ./build/mmtk/$b.native ${SZ[$b]} 2>&1 >/dev/null | tail -1)
        rss=$(echo $out | cut -d" " -f1); wall=$(echo $out | cut -d" " -f2)
        case $rss in (*[!0-9]*) continue;; esac
        [ $rss -lt $best_rss ] && best_rss=$rss
        awk -v a=$wall -v b=$best_wall "BEGIN{exit !(a<b)}" && best_wall=$wall
      done
      [ $best_rss -lt 99999999 ] && echo "{\"bench\":\"$b\",\"side\":\"d\",\"label\":\"h${h}n${nm}\",\"rss_kb\":$best_rss,\"wall_s\":$best_wall}" >> $OUT/pareto.ndjson
    done
  done
  log "pareto $b"
done
log "=== WCOMP4 COMPLETE"
touch $OUT/DONE
