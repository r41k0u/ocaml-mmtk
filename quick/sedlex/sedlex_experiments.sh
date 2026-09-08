#!/usr/bin/env bash
# sedlex investigation reproducer — three discriminators for "why is sedlex ~6x under Bactrian":
#   1. nursery-size sweep (long-lived sedlex vs short-lived binarytrees, both runtimes)
#   2. remembered-set growth vs n and vs nursery size (probed build: MMTK_REMSET_DEBUG)
#   3. stage "coloring": busy-wait injection per GC stage (probed build: MMTK_SPIN_STAGE/NS)
# Usage: sedlex_experiments.sh <results-dir> [stages]   stages ⊆ {nursery,control,remset,coloring,cycles,vanilla}
# Env: MMTK_SEDLEX (Bactrian sedlex exe), MMTK_SEDLEX_PROBE (probed exe), VAN_SEDLEX (vanilla exe),
#      MMTK_BT / VAN_BT (binarytrees natives), OLLY (olly binary), CORES (taskset list)
set -u
R=${1:?results dir}; STAGES=${2:-nursery control remset coloring cycles vanilla}; mkdir -p "$R"
MMTK_SEDLEX=${MMTK_SEDLEX:-$HOME/shape/macro/mmtk/sedlex/sedlex_bench.exe}
MMTK_SEDLEX_PROBE=${MMTK_SEDLEX_PROBE:-$HOME/shape/macro/mmtk-probe4/sedlex/sedlex_bench.exe}
VAN_SEDLEX=${VAN_SEDLEX:-$HOME/shape/macro/vanilla/sedlex/sedlex_bench.exe}
MMTK_BT=${MMTK_BT:-$HOME/shape/shape-bench/quick/build/mmtk/binarytrees.native}
VAN_BT=${VAN_BT:-$HOME/shape/shape-bench/quick/build_vanilla/binarytrees.native}
OLLY=${OLLY:-$HOME/shape/olly}; CORES=${CORES:-0-13}
PIN="taskset -c $CORES"; SA="setarch $(uname -m) -R"
B="MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_HEAP_SIZE_MB=8192"
want(){ case " $STAGES " in *" $1 "*) return 0;; *) return 1;; esac; }
mmtk_line(){ # mmtk_line <label> <exe> <arg> [env...]  -> "<label> wall=..s rss=..MB | GCs: N (full: F), GC time: T ms"
  local lbl=$1 exe=$2 arg=$3; shift 3
  local out; out=$(env $B "$@" MMTK_VERBOSE=1 timeout 900 /usr/bin/time -f "wall=%e rss_kb=%M" $PIN $SA "$exe" "$arg" 2>&1 >/dev/null)
  local w r g; w=$(grep -oE "wall=[0-9.]+" <<<"$out" | cut -d= -f2); r=$(grep -oE "rss_kb=[0-9]+" <<<"$out" | cut -d= -f2)
  g=$(grep -oE "GCs: [0-9]+ \(full: [0-9]+\), GC time: [0-9]+ ms" <<<"$out"); echo "$lbl wall=${w}s rss=$((${r:-0}/1024))MB | $g"
}
van_line(){ # van_line <label> <exe> <arg> <ocamlrunparam>
  local out; out=$(env OCAMLRUNPARAM=$4,v=0x400 /usr/bin/time -f "wall=%e rss_kb=%M" $PIN "$2" "$3" 2>&1 >/dev/null)
  local w r mi ma pw; w=$(grep -oE "wall=[0-9.]+" <<<"$out" | cut -d= -f2); r=$(grep -oE "rss_kb=[0-9]+" <<<"$out" | cut -d= -f2)
  mi=$(grep -oE "^minor_collections: [0-9]+" <<<"$out" | cut -d" " -f2); ma=$(grep -oE "^major_collections: [0-9]+" <<<"$out" | cut -d" " -f2)
  pw=$(grep -oE "promoted_words: [0-9]+" <<<"$out" | cut -d" " -f2); echo "$1 wall=${w}s rss=$((${r:-0}/1024))MB minors=$mi majors=$ma promoted_w=$pw"
}
if want nursery; then { for mb in 2 4 8 16 64 256; do for cfg in default off; do e=""; [ $cfg = off ] && e="MMTK_FULL_GC_CADENCE=100000"
    mmtk_line "bactrian nursery=${mb}MB backstop=$cfg" "$MMTK_SEDLEX" 1000000 MMTK_NURSERY=Fixed:$((mb*1048576)) $e; done; done
  for words in 262144 524288 1048576 2097152 8388608 33554432; do van_line "vanilla nursery=$((words*8/1048576))MB" "$VAN_SEDLEX" 1000000 "o=500,s=$words"; done; } | tee "$R/nursery_sweep.txt"; fi
if want control; then { for mb in 2 4 8 16 64; do mmtk_line "bactrian bt nursery=${mb}MB" "$MMTK_BT" 20 MMTK_HEAP_SIZE_MB=192 MMTK_NURSERY=Fixed:$((mb*1048576)); done
  for words in 262144 524288 1048576 2097152 8388608; do van_line "vanilla bt nursery=$((words*8/1048576))MB" "$VAN_BT" 20 "o=500,s=$words"; done; } | tee "$R/bt_control.txt"; fi
if want remset; then for n in 500000 1000000 2000000; do for mb in 2 16 256; do
    env $B MMTK_NURSERY=Fixed:$((mb*1048576)) MMTK_REMSET_DEBUG=1 MMTK_VERBOSE=1 $PIN $SA "$MMTK_SEDLEX_PROBE" $n 2>&1 >/dev/null | grep -E "^\[probe\]|GCs:" > "$R/remset.$n.$mb.log"
    echo "remset n=$n nursery=${mb}MB: $(grep -c '^\[probe\]' "$R/remset.$n.$mb.log") GCs, last: $(grep '^\[probe\]' "$R/remset.$n.$mb.log" | tail -1 | cut -c1-160)"; done; done | tee "$R/remset_summary.txt"; fi
if want coloring; then { echo "stage ns wall_s"
  for cfg in default off; do e=""; [ $cfg = off ] && e="MMTK_FULL_GC_CADENCE=100000"
    # delays sized to the ~1 s run-to-run noise: per-object stages 100-400 ns (x ~63M), per-pause stages 10-40 ms (x ~500), fulls 0.5-1 s (x ~11)
    for spec in "none:0" "nursery_pause:10000000 20000000 40000000" "full_pause:500000000 1000000000" "cycle_pause:500000000" "object_copy:100 200 400" "scan_object:100 200 400" "modbuf_object:1000000" "mark_quantum:1000000 4000000" "sweep_quantum:1000000 4000000"; do
      st=${spec%%:*}; for ns in ${spec#*:}; do
        out=$(env $B $e MMTK_SPIN_STAGE=$st MMTK_SPIN_NS=$ns /usr/bin/time -f "wall=%e" $PIN $SA "$MMTK_SEDLEX_PROBE" 1000000 2>&1 >/dev/null)
        echo "$cfg $st $ns $(grep -oE "wall=[0-9.]+" <<<"$out" | cut -d= -f2)"; done; done; done; } | tee "$R/coloring.txt"; fi
if want cycles; then # direct per-stage rdtsc accounting (probed build, MMTK_STAGE_CYCLES=1); the last [cycles] line is cumulative
  for run in "default:1000000:" "off:1000000:MMTK_FULL_GC_CADENCE=100000" "default:2000000:" "off:2000000:MMTK_FULL_GC_CADENCE=100000"; do
    cfg=${run%%:*}; rest=${run#*:}; n=${rest%%:*}; e=${rest#*:}
    env $B $e MMTK_STAGE_CYCLES=1 MMTK_VERBOSE=1 /usr/bin/time -f "wall=%e" $PIN $SA "$MMTK_SEDLEX_PROBE" $n 2>&1 >/dev/null | grep -E "^\[cycles\]|GCs:|wall=" | tail -3 > "$R/cycles.$cfg.$n.txt"
    echo "cycles $cfg n=$n: $(grep -E 'wall=|GCs:' "$R/cycles.$cfg.$n.txt" | tr '\n' ' ')"; done; fi
if want vanilla; then for n in 500000 1000000 2000000; do $PIN env OCAMLRUNPARAM=o=500 "$OLLY" trace --format=json "$R/vanilla.$n.trace.json" "$VAN_SEDLEX $n" >/dev/null 2>&1
    python3 "$(dirname "$0")/trace_split.py" "$R/vanilla.$n.trace.json" > "$R/vanilla.$n.phases.txt"; echo "vanilla n=$n: $(grep -E '^minor |^major ' "$R/vanilla.$n.phases.txt" | tr -s ' ' | tr '\n' ';')"; done | tee "$R/vanilla_phases.txt"; fi
echo "EXPERIMENTS-DONE -> $R"
