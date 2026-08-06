# quick — the quick-decision GC benchmark panel (see README.md "Quick panel").
#
# Builds the ten panel benches with the in-tree fork compiler. Two outputs per
# bench (like the CLBG suite):
#   build/<b>.byte    bytecode  (any MMTk plan; correctness smoke + goldens)
#   build/<b>.native  native    (Immix-family plans; what quickbench.py times)
#
# For an A/B feature run (e.g. no-zero OFF vs ON) build each variant's benches
# into its OWN directory and point quickbench.py --bin-a/--bin-b at them:
#   make -C quick native BUILD=/path/off OCAMLOPT=<off-tree>/ocamlopt.opt ...
#   make -C quick native BUILD=/path/on  OCAMLOPT=<on-tree>/ocamlopt.opt  ...
#
# Override the toolchain for CI (bytecode-only build):
#   make -C quick bytecode OCAMLC="$(ROOT)/runtime/ocamlrun $(ROOT)/ocamlc"

# The benchmarks branch is checked out into <fork>/benchmarks/clbg/ (see the CLBG
# README + clbg.yml), so quick/ sits at <fork>/benchmarks/clbg/quick/ and the fork
# tree is three levels up. (Override ROOT/OCAMLC/OCAMLOPT for any other layout,
# e.g. a standalone worktree.)
ROOT     := $(abspath ../../..)
OCAMLC   ?= $(ROOT)/ocamlc.opt
OCAMLOPT ?= $(ROOT)/ocamlopt.opt
STDLIB   ?= $(ROOT)/stdlib
BUILD    ?= build

SEQ_BENCHES := binarytrees nbody fannkuchredux spectralnorm mandelbrot \
               matrix_multiplication LU_decomposition kb
# chameneos_redux was missing here while quickbench.py, mkgolden.sh and
# PARITY_HEAPS all list it, so `make native` never built it and the panel
# silently reported it as n/a — hiding the effect-handler/fiber workload, which
# is where the sharpest multi-domain Bactrian pathology shows up.
PAR_BENCHES := par_spectralnorm par_matmul par_binarytrees chameneos_redux
BENCHES     := $(SEQ_BENCHES) $(PAR_BENCHES)
BYTECODE := $(addprefix $(BUILD)/,$(addsuffix .byte,$(BENCHES)))
NATIVE   := $(addprefix $(BUILD)/,$(addsuffix .native,$(BENCHES)))

# .cmi is shared between byte and native; serialise to avoid a race on it.
.NOTPARALLEL:

.PHONY: all bytecode native golden clean
all: bytecode native
bytecode: $(BYTECODE)
native: $(NATIVE)

$(BUILD):
	mkdir -p $(BUILD)

# Compile inside $(BUILD) on a copy of the source, so OCaml's intermediates
# (.cmi/.cmo/.cmx/.o) land in $(BUILD) (git-ignored) and src/ stays clean.
$(BUILD)/%.byte: src/%.ml | $(BUILD)
	cp $< $(BUILD)/$*.ml
	cd $(BUILD) && OCAMLLIB=$(STDLIB) $(OCAMLC) -I $(STDLIB) -o $*.byte $*.ml

$(BUILD)/%.native: src/%.ml | $(BUILD)
	cp $< $(BUILD)/$*.ml
	cd $(BUILD) && OCAMLLIB=$(STDLIB) $(OCAMLOPT) -I $(STDLIB) -o $*.native $*.ml

# ---- instrumented panel (GC space-time shape: D2 pacing + D3 MMU) ----------
# `make probe BUILD=<dir>` builds the SAME benchmarks with lib/probe.ml linked
# and its per-iteration hook activated.
#
# src/ keeps a bare `(*PROBE*)` marker at each benchmark's per-iteration site.
# It is an ordinary comment, so the plain panel above still compiles unchanged
# and stays stdlib-only — the published numbers carry no probe cost, not even a
# disabled branch. This rule rewrites the marker into a real call, so the
# instrumented binaries are a separate artifact built from the same source.
#
# Native only: under bytecode the tick path costs 10 words/tick (no float
# unboxing) and would corrupt the allocation odometer that D2 divides by. The
# probe refuses to arm there; see lib/probe.ml.
UNIXDIR ?= $(ROOT)/otherlibs/unix
PROBE_BENCHES ?= binarytrees kb par_binarytrees
PROBED := $(addprefix $(BUILD)/,$(addsuffix .probe.native,$(PROBE_BENCHES)))

.PHONY: probe
probe: $(PROBED)

$(BUILD)/%.probe.native: src/%.ml lib/probe.ml | $(BUILD)
	cp lib/probe.ml $(BUILD)/probe.ml
	sed 's|(\*PROBE\*)|Probe.tick ();|' $< > $(BUILD)/$*_probe.ml
	cd $(BUILD) && OCAMLLIB=$(STDLIB) $(OCAMLOPT) -I $(STDLIB) -I $(UNIXDIR) \
	    unix.cmxa probe.ml $*_probe.ml -o $*.probe.native

# Regenerate golden outputs at the panel (perf) sizes (native, GenImmix). Keep
# in sync with quickbench.py perf_args. (Set LINK=bytecode for a bytecode run.)
golden: native
	./mkgolden.sh

clean:
	rm -rf build
