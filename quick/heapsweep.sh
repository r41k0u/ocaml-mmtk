#!/usr/bin/env bash
# heapsweep — D5: throughput vs MEASURED peak RSS, vanilla against the MMTk plans.
#
# Why this is a sweep and not a point. Vanilla paces major work by ALLOCATED
# WORDS (work_counter chasing alloc_counter, major_gc.c:1027-1054); MMTk triggers
# on SPACE OCCUPANCY (GCTriggerPolicy::is_gc_required(space_full, SpaceStats),
# polled only from the page-acquisition path, policy/space.rs:124,307). The two
# respond to different independent variables, so their relative collection rates
# flip with the operating point rather than differing by a constant — vanilla ran
# 61 majors to MMTk's 32 on binarytrees here, while SCALABILITY.md UPDATE 4 saw
# vanilla complete ZERO where MMTk ran 807. One heap size cannot tell "the pacing
# laws match" from "they happen to cross here".
#
# The fork imitates stock's SET POINT (MATURE_PRESSURE_OVERHEAD_PCT = 120 ~
# space_overhead) while keeping a SPACE trigger. Prediction: congruent curves if
# the law matches; agreement at one point only if just the set point does.
#
# X axis is measured peak RSS, because vanilla has no heap cap: the fork sweeps
# MMTK_HEAP_SIZE_MB, vanilla sweeps OCAMLRUNPARAM o= (space_overhead percent),
# and both are plotted against what they actually occupied.
#
# Floor: 56 MiB. Below that binarytrees-20 does not merely thrash, it dies — a
# clean Out_of_memory at 32 MiB but a nondeterministic SEGFAULT through 36-52 MiB
# (see NOTES). Sweeping into that band would mix a crash bug into the curve.
set -u
cd "$(dirname "$0")"

OUT=${OUT:-$PWD/sweep.ndjson}
REPS=${REPS:-5}
BENCHES=${BENCHES:-"binarytrees kb"}
PLANS=${PLANS:-"GenImmix Bactrian"}
HEAPS=${HEAPS:-"64 96 128 192 256 384 512 768 1024"}
OVERHEADS=${OVERHEADS:-"40 60 80 120 200 300 500"}
THREADS=${THREADS:-4}
QB="uv run quickbench.py"

echo "heapsweep -> $OUT   reps=$REPS threads=$THREADS"
echo "  benches:   $BENCHES"
echo "  MMTk:      plans=$PLANS heaps=$HEAPS MiB"
echo "  vanilla:   space_overhead=$OVERHEADS %"
echo

# --resume makes every invocation idempotent, so the whole sweep can be
# interrupted and restarted with the same command.
for H in $HEAPS; do
  echo "### MMTk heap ${H} MiB"
  $QB seq --benches "$BENCHES" --bin-a "$PWD/build_mmtk" --label-a mmtk \
      --plans "$PLANS" --heap "$H" --threads "$THREADS" \
      --reps "$REPS" --warmup 1 --gc --resume --no-plot \
      --json "$OUT" 2>&1 | grep -E "^(binarytrees|kb) " || true
done

for O in $OVERHEADS; do
  echo "### vanilla space_overhead ${O}%"
  $QB seq --benches "$BENCHES" --vanilla "$PWD/build_vanilla" \
      --ocamlrunparam "o=$O" --reps "$REPS" --warmup 1 --gc --resume --no-plot \
      --json "$OUT" 2>&1 | grep -E "^(binarytrees|kb) " || true
done

echo
echo "done -> $OUT ($(grep -c . "$OUT" 2>/dev/null || echo 0) cells)"
