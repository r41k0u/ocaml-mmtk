#!/usr/bin/env bash
# replicate.sh — reproduce the ocaml-mmtk / Bactrian-vs-Vanilla measurements
# (D1 CPU, D2 pacing, D3 pauses, D4 footprint, D5 space-time) and regenerate
# the presentation charts, starting from a fresh Linux x86_64 machine.
#
# Usage:
#   bash replicate.sh              # everything: setup + build + run + charts
#   STAGES="run charts" bash replicate.sh    # rerun only selected stages
#
# Stages (each is idempotent; a stamp file in $WORK/.stamps skips completed work):
#   deps     — check/install prerequisites (prompts for sudo where needed)
#   vanilla  — opam switch with stock OCaml 5.5.0
#   fork     — clone + build ocaml-mmtk (MMTk always-on OCaml 5.5)
#   bench    — build the benchmark panel under both runtimes
#   run      — D1/D2/D3/D4/D5 batteries (results into $WORK/results)
#   charts   — regenerate the presentation figures (into $WORK/charts)
#
# Requirements/notes:
#   * Hardware perf counters: kernel.perf_event_paranoid must be <= 2 for the
#     cycle/instruction measurements. The script offers the sysctl; without it
#     the run falls back to wall-clock and says so in the output.
#   * Results are machine-dependent; the paper's numbers are from a dual
#     Xeon Gold 5120, runs pinned to one socket's physical cores. The script
#     pins to cores 0-(NCORES-1) of node 0 by default (TASKSET= to override).
#   * The JCC-erratum alignment flag is applied to the fork build (as in the
#     paper). Applying it to the opam-built vanilla requires a source rebuild;
#     without it, expect up to ±15% layout noise on matmul-class benches.

set -euo pipefail

WORK="${WORK:-$HOME/mmtk-replication}"
JOBS="${JOBS:-$(nproc)}"
STAGES="${STAGES:-deps vanilla fork bench run charts}"
FORK_URL="${FORK_URL:-https://github.com/r41k0u/ocaml-mmtk.git}"
FORK_BRANCH="${FORK_BRANCH:-shape/tweaks}"
BENCH_BRANCH="${BENCH_BRANCH:-shape/instruments}"
SWITCH="${SWITCH:-replication-5.5.0}"
mkdir -p "$WORK/.stamps" "$WORK/results" "$WORK/charts"
LOG="$WORK/replicate.log"
say(){ echo "[replicate] $*" | tee -a "$LOG"; }
stamp(){ touch "$WORK/.stamps/$1"; }
stamped(){ [ -f "$WORK/.stamps/$1" ]; }
want(){ case " $STAGES " in *" $1 "*) return 0;; *) return 1;; esac; }
clone_retry(){ # clone_retry <branch> <dir> — shallow, survives flaky networks
  local t
  for t in 1 2 3; do
    git clone --depth 1 --branch "$1" "$FORK_URL" "$2" && return 0
    say "clone of $2 (branch $1) failed, attempt $t/3 — retrying in 15s"
    rm -rf "$2"; sleep 15
  done
  say "ERROR: could not clone $FORK_URL branch $1"; return 1
}

# Core pinning: first N physical cores of NUMA node 0.
if [ -z "${TASKSET:-}" ]; then
  NCORES=$(lscpu -p=CORE,SOCKET 2>/dev/null | grep -v '^#' | awk -F, '$2==0' | sort -u | wc -l)
  [ "$NCORES" -ge 2 ] || NCORES=$(nproc)
  TASKSET="0-$((NCORES-1))"
fi
say "pinning benchmark runs to cores $TASKSET"

# ---------------------------------------------------------------- deps
if want deps && ! stamped deps; then
  say "stage: deps"
  need=(git curl make gcc g++ pkg-config autoconf python3 python3-venv linux-tools-generic
        opam bubblewrap unzip cmake libffi-dev zlib1g-dev)
  if command -v apt-get >/dev/null; then
    say "installing packages (sudo): ${need[*]}"
    sudo apt-get update -qq && sudo apt-get install -y -qq "${need[@]}" || \
      say "WARNING: package install failed — continuing; missing tools will fail their stage"
  else
    say "non-apt system: ensure equivalents of: ${need[*]}"
  fi
  command -v opam >/dev/null || { say "installing opam"; bash -c "sh <(curl -fsSL https://opam.ocaml.org/install.sh)"; }
  command -v cargo >/dev/null || { say "installing rust"; curl -fsSL https://sh.rustup.rs | sh -s -- -y; }
  . "$HOME/.cargo/env" 2>/dev/null || true
  PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
  if [ "$PARANOID" -gt 2 ]; then
    say "perf_event_paranoid=$PARANOID blocks hardware counters."
    say "run:  sudo sysctl kernel.perf_event_paranoid=1   then re-run; falling back to wall-clock for now."
  fi
  stamp deps
fi

# ---------------------------------------------------------------- vanilla
if want vanilla && ! stamped vanilla; then
  say "stage: vanilla (opam switch $SWITCH, ocaml 5.5.0)"
  opam init -a --bare 2>/dev/null || true
  opam switch list 2>/dev/null | grep -q "$SWITCH" || opam switch create "$SWITCH" ocaml-base-compiler.5.5.0 -y
  opam install -y --confirm-level=unsafe-yes --switch="$SWITCH" dune runtime_events_tools || \
    say "WARNING: olly (runtime_events_tools) unavailable — vanilla pause tails will be skipped"
  stamp vanilla
fi
VOPT(){ opam exec --switch="$SWITCH" -- "$@"; }

# ---------------------------------------------------------------- fork
if want fork && ! stamped fork; then
  say "stage: fork (ocaml-mmtk @ $FORK_BRANCH — this builds a full OCaml; ~15-30 min)"
  cd "$WORK"
  [ -d ocaml-mmtk ] || clone_retry "$FORK_BRANCH" ocaml-mmtk
  cd ocaml-mmtk
  sub=0
  for t in 1 2 3; do
    git submodule update --init --depth 1 gc/mmtk-core && { sub=1; break; }
    say "submodule fetch failed, attempt $t/3 — retrying in 15s"; sleep 15
  done
  [ "$sub" = 1 ]
  export PATH="$HOME/.cargo/bin:$PATH"
  ./configure --prefix="$WORK/mmtk-install"
  setarch "$(uname -m)" -R make -j"$JOBS" world.opt
  make install
  stamp fork
fi
FORKBIN="$WORK/mmtk-install/bin"

# ---------------------------------------------------------------- bench
if want bench && ! stamped bench; then
  say "stage: bench (quick panel under both runtimes)"
  cd "$WORK"
  [ -d benches ] || clone_retry "$BENCH_BRANCH" benches
  Q="$WORK/benches/quick"
  make -C "$Q" native BUILD=build_vanilla \
    OCAMLOPT="$(VOPT which ocamlopt)" STDLIB="$(VOPT ocamlc -where)"
  make -C "$Q" native BUILD=build/mmtk \
    OCAMLOPT="$FORKBIN/ocamlopt" STDLIB="$("$FORKBIN/ocamlc" -where)"
  stamp bench
fi
Q="$WORK/benches/quick"

# ---------------------------------------------------------------- run
if want run; then
  say "stage: run"
  cd "$Q"
  R="$WORK/results"; SA="setarch $(uname -m) -R"
  B="MMTK_PLAN=Bactrian MMTK_HEAP_SIZE_MB=192 MMTK_THREADS=1"
  B2="$B MMTK_NURSERY=Fixed:2097152"
  declare -A SZ=( [binarytrees]=20 [nbody]=20000000 [fannkuchredux]=11
    [spectralnorm]=3000 [mandelbrot]=4000 [matrix_multiplication]=768
    [LU_decomposition]=900 [kb]=50 [mature_mutation]=8 [weak_memo]=800 [fragmed]=150 )
  PANEL="nbody fannkuchredux mandelbrot weak_memo matrix_multiplication spectralnorm kb LU_decomposition binarytrees"
  ADVERSARIAL="mature_mutation fragmed"
  PERF_OK=0; perf stat -e cycles,instructions -x, -- true >/dev/null 2>&1 && PERF_OK=1
  [ $PERF_OK = 1 ] || say "WARNING: perf unavailable — recording wall-clock instead of cycles"
  measure(){ # measure <outprefix> <env-string> <binary> <arg>
    local out=$1 envs=$2 bin=$3 arg=$4 r
    for r in 1 2 3; do
      if [ $PERF_OK = 1 ]; then
        env $envs perf stat -e cycles,instructions -x, -o "$out.r$r.stat" -- \
          taskset -c "$TASKSET" $SA "$bin" "$arg" >/dev/null 2>/dev/null
      else
        env $envs /usr/bin/time -f %e -o "$out.r$r.wall" -- \
          taskset -c "$TASKSET" $SA "$bin" "$arg" >/dev/null 2>/dev/null
      fi
    done
    env $envs /usr/bin/time -f %M taskset -c "$TASKSET" $SA "$bin" "$arg" >/dev/null 2>"$out.rss"
  }
  say "run: correctness gate (byte-identical outputs)"
  for b in $PANEL $ADVERSARIAL; do
    env $B $SA ./build/mmtk/$b.native "${SZ[$b]}" 2>/dev/null | cmp -s - "golden/$b.out" \
      || { say "GOLDEN MISMATCH on $b — aborting (a correctness bug beats any measurement)"; exit 1; }
  done
  say "run: D1/D4 (both runtimes, 3 reps + RSS; UP-oldify on the Bactrian side as in the paper)"
  for b in $PANEL $ADVERSARIAL; do
    measure "$R/v.$b"  "OCAMLRUNPARAM=o=500"      "./build_vanilla/$b.native" "${SZ[$b]}"
    measure "$R/d.$b"  "$B MMTK_UP_OLDIFY=1"      "./build/mmtk/$b.native"    "${SZ[$b]}"
    say "  done $b"
  done
  say "run: D2 (major-collection counts) + D3 (pause streams)"
  env $B2 MMTK_VERBOSE=1 $SA ./build/mmtk/binarytrees.native 20 >/dev/null 2>"$R/d2m.bt.verbose"
  env $B  MMTK_VERBOSE=1 $SA ./build/mmtk/binarytrees.native 20 >/dev/null 2>"$R/ddef.bt.verbose"
  env OCAMLRUNPARAM=o=500,v=0x400 $SA ./build_vanilla/binarytrees.native 20 >/dev/null 2>"$R/v.bt.verbose"
  for cfg in "d2m $B2" "ddef $B"; do
    set -- $cfg; tag=$1; shift; envs="$*"
    for b in binarytrees kb; do
      env $envs MMTK_PAUSE_LOG="$R/$tag.$b.pause.ndjson" taskset -c "$TASKSET" $SA \
        ./build/mmtk/$b.native "${SZ[$b]}" >/dev/null 2>/dev/null
    done
  done
  if VOPT which olly >/dev/null 2>&1; then
    for b in binarytrees kb; do
      VOPT olly latency -o "$R/v.$b.olly.json" \
        "env OCAMLRUNPARAM=o=500 taskset -c $TASKSET $SA ./build_vanilla/$b.native ${SZ[$b]}" \
        >/dev/null 2>&1 || say "  olly failed on $b (vanilla pause tail skipped)"
    done
  fi
  say "run: D5 sweep (vanilla s x o grid; Bactrian heap + overhead dials)"
  for b in binarytrees kb; do
    for sw in 262144 524288 1048576 2097152; do for o in 80 120 200 500; do
      measure "$R/v5.$b.s${sw}o${o}" "OCAMLRUNPARAM=s=$sw,o=$o" "./build_vanilla/$b.native" "${SZ[$b]}"
    done; done
    for h in 64 96 128 160 192 256; do
      measure "$R/d5.$b.fix$h" "MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_HEAP_SIZE_MB=$h" \
        "./build/mmtk/$b.native" "${SZ[$b]}"
    done
    for n in 2097152 4194304 8388608 16777216; do for p in 80 120 200 500; do
      measure "$R/d5.$b.n${n}p${p}" \
        "MMTK_PLAN=Bactrian MMTK_THREADS=1 MMTK_NURSERY=Fixed:$n MMTK_GC_TRIGGER=SpaceOverheadSize:33554432,4294967296,$p" \
        "./build/mmtk/$b.native" "${SZ[$b]}"
    done; done
    say "  D5 grid done: $b"
  done
  say "run: complete — raw data in $R"
fi

# ---------------------------------------------------------------- charts
if want charts; then
  say "stage: charts"
  [ -d "$WORK/venv" ] || { python3 -m venv "$WORK/venv"; "$WORK/venv/bin/pip" -q install matplotlib; }
  "$WORK/venv/bin/python" "$(dirname "$0")/replicate_charts.py" "$WORK/results" "$WORK/charts"
  say "charts written to $WORK/charts"
fi
say "all requested stages finished."
