#!/usr/bin/env bash
# eio RSS-over-time: sample RSS every 0.5 s alongside the pause log. Usage: CORES=0-13 eio_rss.sh <outdir> <label:bindir:envs>...
set -u; R=$1; shift; mkdir -p $R; SA="setarch x86_64 -R"; PIN="taskset -c ${CORES:-0-13}"
for spec in "$@"; do label=${spec%%:*}; rest=${spec#*:}; bin=${rest%%:*}; envs=${rest#*:}; [ "$envs" = "$bin" ] && envs=""
  cd $HOME/shape/macro/$bin/eio || { echo "MISSING $bin"; continue; }
  case $bin in vanilla) base="";; *) base="MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_VERBOSE=1 MMTK_PAUSE_LOG=$R/$label.pause.ndjson";; esac
  env $base $envs $PIN $SA ./eio_conc_bench.exe 9000 >/dev/null 2>$R/$label.verbose & pid=$!
  t0=$(date +%s.%N); while kill -0 $pid 2>/dev/null; do echo "$(date +%s.%N) $(ps -o rss= -p $pid 2>/dev/null)"; sleep 0.5; done | awk -v t0=$t0 '{printf "%.1f %d\n", $1-t0, $2/1024}' > $R/$label.rss
  wait $pid; rc=$?; echo "$label rc=$rc peak_rss_MB=$(sort -k2 -n $R/$label.rss | tail -1 | cut -d" " -f2) samples=$(wc -l < $R/$label.rss) | $(grep -h "GCs:" $R/$label.verbose 2>/dev/null)"
done; echo EIO-RSS-DONE
