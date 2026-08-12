# Issues found and fixed on the road to vanilla-equivalence

Every *defect* discovered during the shape campaign (2026-08-06 → 2026-08-12) —
things that were wrong, as opposed to design deltas that were closed (those are
in `CHANGES-AND-TARGETS.md`). Each entry: symptom → root cause → fix → proof.
Ordered by discovery. Commits are on fork `shape/tweaks` / the `gc/mmtk-core`
submodule.

## 1. The poll-trap livelock (the "8.9× catastrophe")

**Symptom:** matmul at a 16 MiB nursery ran 82 G mutator instructions (8.9×
wall) with a single GC; every small-nursery config exploded unpredictably.
**Root cause:** compiler-emitted poll points trap on `young_ptr <= young_limit`
(`jbe`), but every C-side check tested strict `<`. A GC that discarded the TLAB
left the two equal, and an allocation-free compute phase then re-trapped on
*every* poll, each trap running the whole pending-actions machinery and
changing nothing.
**Fix:** the poll-path refill uses the emitted condition (`<=`).
**Proof:** matmul@16M 3.66 s → 0.95 s; objdump of generated-vs-runtime
comparisons was the discriminating evidence.

## 2. Bactrian pretenuring crash: wrong-type allocator downcast

**Symptom:** every GC-ing bench aborted (`allocators.rs:99 unwrap on None`)
once the NonMoving semantic was remapped to mature Immix — even with the
feature knob off.
**Root cause:** two layered bugs. (a) The allocator and space mappings were
built from *different* `ReservedAllocators` sets, shifting the common spaces'
selector indices. (b) With `marksweep_as_nonmoving` enabled, the common
mutator prepare/release path downcasts the NonMoving allocator to
`FreeListAllocator` by semantic — which the remap had pointed at an
`ImmixAllocator`.
**Fix:** both mappings built from one reserved set; the common free-list
allocator reached by selector (`FreeList(0)`) instead of by semantic.
**Proof:** full golden battery; and the fix preserved the
`pending_release_packets` handshake (skipping it deadlocked/aborted — issue 3).

## 3. Remembered-set flood from immediate stores

**Symptom:** pretenured matmul held 81 MB RSS vs vanilla's 18; LD_PRELOAD
tracing showed 46 MB of live remset buffers (721 × 64 KB mallocs).
**Root cause:** our `caml_initialize`/`caml_modify` barriers recorded *every*
initialising store; stock's ref-table only admits actual pointers. Born-mature
int arrays buffered one remset entry per slot.
**Fix:** gate the generational region barrier on `Is_block(stored value)` at
all three sites (the SATB half deliberately not gated — it greys old
referents).
**Proof:** RSS 81 → 35.6 MB; outputs byte-identical incl. forced-concurrent
canaries.

## 4. Header-sentinel forwarding broke the infix disambiguator (kb SIGSEGV)

**Symptom:** kb segfaulted on the GC worker the moment forwarding stopped
writing side-metadata state.
**Root cause:** the binding's `Infix_tag`-vs-forwarding-pointer check read the
side forwarding bits — no longer written under the sentinel protocol. A
forwarding pointer whose low byte spelled 0xf9 parsed as a genuine infix
header → garbage parent offset → wild dereference.
**Fix:** the check discriminates by value range (header word vs heap start),
valid in *every* mode — and cheaper (drops a side load + `is_mapped` probe per
infix check, retiring that whole SIGSEGV hazard class, GH issue 12 lineage).
**Proof:** kb clean across all gates; bt had masked the bug (no closures in
its hot path) — the multi-bench gate battery caught it.

## 5. Post-FinalMark spurious "emergency" Full pauses

**Symptom:** under sliced marking, BACTRIAN_TRACE showed `schedule Full,
emergency=true` immediately after every `end FinalMark` — 15 extra STW Fulls
per bt@2M run.
**Root cause:** the scheduler's parked-workers self-request raced FinalMark's
marking-state clear and requested a second, zero-allocation collection —
which `set_collection_kind` reads as an emergency (no allocation succeeded
since the last GC) and escalates to a stop-the-world Full.
**Fix:** the self-request is suppressed when marking is confined to pauses
(sliced mode never needs it — marking can only finish *inside* a pause).
**Proof:** trace shows 17 InitialMark / 16 FinalMark / 0 spurious Fulls.

## 6. Cycle pacing never reset at FinalMark

**Symptom:** sliced/concurrent cycles ran at half vanilla's cadence; the bug
was masked by issue 5's accidental counter resets until that was fixed.
**Root cause:** the pacing law recognised only `Pause::Full` as a major
collection: a completed concurrent cycle (FinalMark) neither reset the
mature-pressure baseline nor the allocation budget, and the budget was
measured from cycle *end* rather than cycle *start* (stock pacing semantics).
**Fix:** completion resets the baseline; cycle start resets the allocation
budget; a monolithic Full is both at once (that mode bit-identical).
**Proof:** D2 calibration became possible at all; bt@2M now runs 28 cycles vs
vanilla's 29.

## 7. The code-layout lottery (the "fork-ambient 20%" mystery)

**Symptom:** matmul/LU/kb/fannkuch mutator cycles moved ±5–12 % between
semantically identical builds; every data-side PMU counter flat;
NoGC-reproducible; a 17-hypothesis refutation ledger had failed to explain it.
**Root cause:** the Skylake JCC erratum. ocamlopt aligns functions to 16
bytes, so upstream `.text` size decides whether a function lands at 0 or 16
mod 32. On the bad draw, matmul's inner-loop branch touched a 32-byte
boundary; the erratum microcode excludes that window from the uop cache — DSB
coverage 99.4 % → 1.7 %, all data counters untouched.
**Fix:** `-mbranches-within-32B-boundaries` on **both** OCaml toolchains and
the Rust staticlib (a methodology fix — the erratum is a CPU artifact, not a
GC property; vanilla's own fannkuch build was a victim, −16 % under
mitigation).
**Proof:** instruction-level geometry both builds; causal 16-byte `.text`
shift (DSB ×13); post-mitigation DSB 99.3 %/99.2 % and matmul deterministic at
0.98×.

## 8. Store-side blindness in the measurement methodology (meta-issue)

**Symptom:** the historical fork-ambient ledger claimed "all PMU counters at
parity" for LU while a 1.2 G-cycle gap persisted.
**Root cause:** every counter measured was load-side (LLC-loads, instructions,
L1d loads); the gap was in *stores* (`l2_rqsts.rfo_miss` 418 K vs 7.7 M — 18×,
invisible to all of them).
**Fix (methodological):** top-down decomposition first, then the event family
the top-down points at; store-side events are now part of the standard
battery.
**Proof:** LU's gap decomposed same-day into the allocation-frontier warmth
mechanism once the right family was measured.

## Found, verified pre-existing, and logged (not from this campaign's changes)

- **StickyImmix `pending_release_packets` underflow** — kb and the ocamlc
  compile repro abort at `epilogue.rs:11` with the counter at −2; reproduces
  identically at the pre-campaign tree. Suspect: the `marksweep_as_nonmoving`
  release protocol under fused pauses. Open item, NOTES 2026-08-10.
