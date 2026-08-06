#!/usr/bin/env python3
"""gcsplit — D1 CPU budget: split sampled CPU three ways, W / G / C.

KC's framing of the shape argument is that what matters is aggregate CPU spent
doing work versus aggregate CPU spent doing GC — a ratio that does not care
whether GC work is interleaved into the mutator domains (vanilla) or handed to
dedicated worker threads (Bactrian). That invariance is what makes "dedicated
GC workers are fine" a claim rather than a concession, so this is the headline
dimension and it has to be measured the same way on both runtimes.

perf symbol attribution is that common instrument: one tool, both runtimes, and
the same definition of what counts as GC. It works precisely because it asks
"which code ran", not "which thread ran it".

THREE BUCKETS, NOT TWO
----------------------
  W  mutator — the program's own work
  G  GC      — tracing, sweeping, copying, barriers' slow paths
  C  coordination-spin — lock contention, spin waits, futex, park/unpark

C must be reported separately. Folding it into W would shrink the measured GC
fraction and make the shape look closer than it is — a bias pointing exactly
the way the paper argues, which is the one direction we cannot afford. The
bucket is known to be large on the MMTk side: SCALABILITY.md UPDATE 4 measured
context switches rising 3.9k -> 76k -> 634k at d1/8/24 and 8.7% of cycles in
Mutex::lock_contended at d24.

Note what C does *not* cover: a thread blocked in a futex burns no CPU at all,
so it cannot appear in any CPU profile. Blocked time shows up as wall time in
which the mutator is not progressing, which is D3's (MMU) business. D1 covers
CPU-consuming work, D3 covers stalled time; together they are complete and
neither double-counts.

Every rule below is auditable: --show-unmatched lists the heaviest symbols that
fell through to W, so a symbol that should have been G or C cannot hide.

JUDGMENT CALLS, stated because they move the headline number
------------------------------------------------------------
Three classes are genuinely debatable. Each is resolved the same way on both
runtimes, which is what keeps the comparison fair even if a reviewer would
draw the line elsewhere:

  * Write barriers (caml_modify, caml_initialize, and MMTk's barrier slow
    paths) count as G. They are work the mutator performs on the collector's
    behalf, and they are the cost RQ1 is about. Vanilla's caml_modify and the
    fork's barrier both land in G, so neither side is favoured.
  * Allocation slow paths (caml_alloc_shr, mmtk_ocaml_refill_tlab) count as G.
    Both are the GC's allocator doing bookkeeping, and again both sides are
    treated alike. A reviewer preferring "allocation is mutator work" can move
    both patterns to W and the comparison stays symmetric.
  * Kernel page work (clear_page_erms and friends) stays in W. It is demand
    zeroing that both runtimes incur, and attributing it to the collector
    would flatter whichever side touches fewer fresh pages.

Usage:
    perf record -q -g --call-graph=fp -o perf.data -- CMD ...
    gcsplit.py perf.data                     # or: gcsplit.py --report report.txt
    gcsplit.py perf.data --json out.json --show-unmatched
"""

import argparse
import json
import re
import subprocess
import sys

# Ordered: first matching bucket wins, so C is tested before G before W.
# Patterns are matched case-insensitively against the symbol name.

C_PATTERNS = [
    r"caml_mmtk_park",              # the binding's mutator park on STW
    r"lock_contended",              # Rust std Mutex slow path
    r"parking_lot",
    r"\bfutex",                     # kernel futex paths
    r"__lll_lock", r"__lll_unlock",
    r"pthread_mutex", r"pthread_cond", r"pthread_barrier",
    r"caml_plat_.*(lock|wait|spin|barrier)",
    r"caml_thread_yield",
    r"sched_yield",
    r"stw_.*(barrier|wait)",
    r"caml_try_run_on_all_domains",  # vanilla's all-domains rendezvous
    r"caml_wait_.*domain",
    r"osq_lock", r"rwsem_",         # kernel lock paths
]

G_PATTERNS = [
    # --- vanilla OCaml's own collector ---
    r"^caml_darken", r"mark_slice_darken", r"do_some_marking",
    r"^mark$", r"^sweep$", r"caml_sweep", r"caml_major_collection_slice",
    r"major_collection_slice", r"caml_empty_minor_heap", r"caml_minor_collection",
    r"oldify", r"caml_do_roots", r"caml_scan_stack", r"caml_final_",
    r"ephe_(mark|sweep)", r"caml_shared_try_alloc", r"pool_sweep",
    r"caml_compact", r"caml_cycle_heap", r"caml_alloc_shr",
    # --- MMTk ---
    r"^mmtk", r"_ZN4mmtk", r"scan_ocaml_object", r"scan_object",
    r"trace_object", r"process_edges", r"ProcessEdges",
    r"ImmixSpace", r"CopySpace", r"MarkSweep", r"immixspace",
    r"GCWorker", r"gc_work", r"WorkBucket", r"scheduler",
    r"forward_object", r"copy_object", r"^caml_mmtk_(?!park)",
    r"bzero_metadata", r"side_metadata", r"SweepChunk",
    # --- barriers' out-of-line slow paths (write barrier work IS GC work) ---
    r"caml_modify", r"caml_initialize", r"caml_write_barrier",
]

C_RE = [re.compile(p, re.I) for p in C_PATTERNS]
G_RE = [re.compile(p, re.I) for p in G_PATTERNS]


def classify(sym):
    for r in C_RE:
        if r.search(sym):
            return "C"
    for r in G_RE:
        if r.search(sym):
            return "G"
    return "W"


REPORT_LINE = re.compile(r"^\s*(\d+\.\d+)%\s+(?:\S+\s+)?(?:\[[.k]\]\s+)?(.+?)\s*$")


def parse_report(text):
    """Yield (percent, symbol) from `perf report --stdio` output."""
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = REPORT_LINE.match(line)
        if m:
            try:
                yield float(m.group(1)), m.group(2).strip()
            except ValueError:
                continue


def perf_report(data_path):
    cmd = ["perf", "report", "--stdio", "--no-children", "-q",
           "-F", "overhead,sym", "-i", data_path]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"perf report failed:\n{p.stderr.strip()}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", nargs="?", help="perf.data file")
    ap.add_argument("--report", help="pre-generated `perf report --stdio` text")
    ap.add_argument("--json", help="write the split as JSON here")
    ap.add_argument("--show-unmatched", action="store_true",
                    help="list the heaviest symbols that fell through to W")
    ap.add_argument("--label", default="", help="tag for the JSON record")
    a = ap.parse_args()

    if not a.data and not a.report:
        ap.error("give a perf.data path or --report FILE")

    text = open(a.report).read() if a.report else perf_report(a.data)

    buckets = {"W": 0.0, "G": 0.0, "C": 0.0}
    per_symbol = {"W": [], "G": [], "C": []}
    for pct, sym in parse_report(text):
        b = classify(sym)
        buckets[b] += pct
        per_symbol[b].append((pct, sym))

    total = sum(buckets.values())
    if total <= 0:
        sys.exit("no samples parsed — is this a perf report with symbols?")

    # Both ratios are reported because they are different claims and a reviewer
    # will ask which one is meant: G/(W+G) ignores coordination entirely,
    # G/(W+G+C) charges it to neither side but keeps it in the denominator.
    gc_frac_excl_c = buckets["G"] / (buckets["W"] + buckets["G"]) if (buckets["W"] + buckets["G"]) else 0.0
    gc_frac_incl_c = buckets["G"] / total

    out = {
        "kind": "cpu_split",
        "label": a.label,
        "pct": {k: round(v, 3) for k, v in buckets.items()},
        "share": {k: round(v / total, 5) for k, v in buckets.items()},
        "gc_fraction_G_over_WG": round(gc_frac_excl_c, 5),
        "gc_fraction_G_over_WGC": round(gc_frac_incl_c, 5),
        "parsed_total_pct": round(total, 3),
    }

    print(f"  W mutator      {buckets['W']:7.2f}%   ({out['share']['W']*100:5.1f}% of parsed)")
    print(f"  G gc           {buckets['G']:7.2f}%   ({out['share']['G']*100:5.1f}%)")
    print(f"  C coordination {buckets['C']:7.2f}%   ({out['share']['C']*100:5.1f}%)")
    print(f"  GC fraction: G/(W+G) = {gc_frac_excl_c:.4f}   G/(W+G+C) = {gc_frac_incl_c:.4f}")

    for b in ("G", "C"):
        top = sorted(per_symbol[b], reverse=True)[:8]
        if top:
            print(f"  top {b}: " + ", ".join(f"{s}({p:.1f}%)" for p, s in top))

    if a.show_unmatched:
        print("  heaviest symbols classified W (audit these for missed G/C):")
        for p, s in sorted(per_symbol["W"], reverse=True)[:25]:
            print(f"    {p:6.2f}%  {s}")

    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
