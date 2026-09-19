#!/usr/bin/env bash
# Working-set sampler: every INTERVAL s, read Referenced (pages touched since the last clear) from smaps_rollup, then clear the referenced bits.
# Output per sample: t_s  wss_MB  rss_MB. Usage: INTERVAL=2 CORES=0-13 eio_wss.sh <outdir> <label:bindir:envs>...
set -u; R=$1; shift; mkdir -p $R; SA="setarch x86_64 -R"; PIN="taskset -c ${CORES:-0-13}"; IV=${INTERVAL:-2}
for spec in "$@"; do label=${spec%%:*}; rest=${spec#*:}; bin=${rest%%:*}; envs=${rest#*:}; [ "$envs" = "$bin" ] && envs=""
  cd $HOME/shape/macro/$bin/eio || { echo "MISSING $bin"; continue; }
  case $bin in vanilla) base="";; *) base="MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_VERBOSE=1 MMTK_PAUSE_LOG=$R/$label.pause.ndjson";; esac
  env $base $envs $PIN $SA ./eio_conc_bench.exe 9000 >/dev/null 2>$R/$label.verbose & pid=$!
  t0=$(date +%s.%N); sleep 0.2; echo 1 > /proc/$pid/clear_refs 2>/dev/null
  while kill -0 $pid 2>/dev/null; do sleep $IV; kill -0 $pid 2>/dev/null || break
    ref=$(awk '/^Referenced:/{print $2}' /proc/$pid/smaps_rollup 2>/dev/null); rss=$(awk '/^Rss:/{print $2}' /proc/$pid/smaps_rollup 2>/dev/null)
    echo "$(date +%s.%N) ${ref:-0} ${rss:-0}"; echo 1 > /proc/$pid/clear_refs 2>/dev/null
  done | awk -v t0=$t0 '{printf "%.1f %d %d\n", $1-t0, $2/1024, $3/1024}' > $R/$label.wss
  wait $pid; rc=$?; echo "$label rc=$rc interval=${IV}s samples=$(wc -l < $R/$label.wss) peak_wss_MB=$(sort -k2 -n $R/$label.wss | tail -1 | cut -d" " -f2) median_wss_MB=$(sort -k2 -n $R/$label.wss | awk '{a[NR]=$2} END{print a[int((NR+1)/2)]}') peak_rss_MB=$(sort -k3 -n $R/$label.wss | tail -1 | cut -d" " -f3) | $(grep -h "GCs:" $R/$label.verbose 2>/dev/null)"
done; echo EIO-WSS-DONE
