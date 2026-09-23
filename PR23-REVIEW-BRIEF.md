# Review brief: fplaunchpad/ocaml-mmtk PR #23 ("[WIP] Making Bactrian GC shape similar to Vanilla GC")

*Prepared 2026-09-22 before the manual review; head now `r41k0u:shape/tweaks` @ 57fb1718d (2026-09-23: hygiene commit, the two August pacing cherry-picks, the binding's quantum-hint removal, submodule at mmtk-core abd1879f6f). Originally written at 053dc04d5,
base `fplaunchpad:5.5+mmtk` @ cbc66e3efd. 123 commits, 97 files, +6054 / −59.*

## 1. Is it up to date?

Yes. The PR head is the fork's `shape/tweaks` at 053dc04d5, which is the last push
(2026-09-21): it carries the binding's marked-live baseline (19ca2fe1c) and the
submodule bump to mmtk-core `0.32-ocaml` @ f7431e4480 (honest pacing + CI fixes,
the head of fplaunchpad/mmtk-core PR #1). The base branch has not moved under it
(0 commits on `5.5+mmtk` that are not in the PR), so no rebase is needed. GitHub
reports it mergeable with state "unstable" (a check is red or pending; I cannot
read which without authentication).

## 2. What is in it, by area

| area | files | lines | what |
|---|---:|---:|---|
| `benchmarks/clbg/build/**` | 72 | +2660 | **compiled ELF binaries** (`*.native`, `*.byte`, plus `val/*` per-plan variants), added by d7e8b6d9f. Build artefacts; there is no `benchmarks/clbg/.gitignore`. |
| `gc/mmtk/binding` | 4 | +801 / −34 | the binding: pacing laws, pause log, UP-trace/oldify, aging, debug knobs |
| `runtime/mmtk.c` (+`memory.c`, `minor_gc.c`, `domain.c`, `array.c`, `caml/mmtk.h`) | 6 | +487 / −13 | runtime side: TLAB refill, mature-direct tick, medium/LOS placement, measurement knobs |
| `gc/mmtk/SHAPE.md`, `gc/mmtk/NOTES.md` | 2 | +1820 | campaign journals (rounds 18–30, dated notes) |
| `docs/ocaml-workshop-2026-abstract.{md,tex}` | 2 | +164 | workshop abstract |
| `CLAUDE.md`, `README.md`, `ROADMAP.md` | 3 | +41 / −9 | project docs; CLAUDE.md is assistant configuration |
| `gc/mmtk/Cargo.toml`, `gc/mmtk/.cargo/config.toml` | 2 | +15 / −4 | features `sticky_immix_non_moving_nursery`, `marksweep_as_nonmoving`; thin LTO + 1 codegen unit; `-x86-branches-within-32B-boundaries` rustflag |
| `gc/mmtk/common`, `gc/mmtk/include`, `Makefile.mmtk`, `.gitmodules`, `gc/mmtk-core` | 6 | +90 / −3 | slot/scanning helpers, build plumbing, submodule pointer |

Commit subjects by prefix: SHAPE 32, binding 24, gc/mmtk-core (submodule bumps) 21,
runtime 15, build 6, NOTES 5, docs 2, other 18. Roughly a third of the history is
journal and bump commits.

## 3. Things to fix or decide before review

*Update (c6b3cbb11, pushed):* items 1–3 are done — the 72 binaries, SHAPE.md and
the workshop draft are out of the tree and gitignored (kept on disk); NOTES.md,
which is an upstream file the campaign had appended to, is back at the base
version with the appended copy kept locally as the ignored `NOTES-campaign.md`;
CLAUDE.md is back at the base version. The PR is now 21 files, +1409 / −55.


1. **Remove the 72 compiled binaries** under `benchmarks/clbg/build/` and add a
   `.gitignore` for that directory. They are ELF executables committed by accident
   in d7e8b6d9f; they bloat the PR and cannot be reviewed.
2. **Decide the fate of the journals.** `SHAPE.md` (1223 lines) and `NOTES.md`
   (597) are the campaign log, not documentation of the shipped design. They also
   contain stale statements: NOTES.md lines 128–129 describe the slicing gate as
   `MMTK_SLICE_MAX_NURSERY_MB` / `MMTK_MAX_QUANTUM_MS`, knobs the core no longer
   has (replaced by `MMTK_SLICE_WORTH_MS` / `MMTK_SLICE_MAX_PAUSE_MS`, and in the
   current core slicing is always feasible unless `MMTK_SLICE_FEASIBLE=1`).
   Either drop them from the PR or keep them as `docs/` history with a header
   saying the design sections are superseded by the code comments.
3. **`CLAUDE.md` does not belong in an upstream PR.** The workshop abstract
   probably does not either.
4. **Build-config changes need a sentence in the PR description:** thin LTO with
   one codegen unit (measured 6 % of GC-worker cycles in outlined slot helpers),
   the two extra mmtk features, and the JCC-erratum rustflag. The last one is a
   layout-determinism measure; reviewers will ask whether it belongs in the
   product build or only in benchmarking builds.
5. **Experiment-only knobs shipped in product code.** Runtime: `MMTK_ALLOC_JITTER`,
   `MMTK_LOS_THRESHOLD`, `MMTK_POLL_DEBUG`, `MMTK_FRONTIER_WARMER`,
   `MMTK_TEST_MALLOC_MEDIUM` ("MEASUREMENT INSTRUMENT ONLY, NEVER a default"),
   `MMTK_BARRIER_COUNT`, `MMTK_MUTATOR_GC_TIME`, `MMTK_TLAB_PREFETCH`. Binding:
   `MMTK_UP_DEBUG`, `MMTK_DEBUG_STACK_CHECK`, `MMTK_DEBUG_ROOT_RACE`,
   `MMTK_NO_TRUSTED_LOADS`. Each is env-gated and off by default, so they are
   harmless at run time, but they are review surface. Worth either a short
   "diagnostic knobs" table in the PR description or a cleanup commit that
   removes the ones whose experiment is over (jitter, LOS threshold, frontier
   warmer, malloc-medium).

## 4. Duplication and split responsibilities between mmtk-core and the binding

Nothing is literally copied between the two repos, but several policies are
implemented on both sides, and a reviewer reading both PRs will ask which side
owns what.

1. **Two pacing laws for the same cycle.** The binding computes a mark-quantum
   *hint* in `hint_mark_quantum` (debt = live ÷ `MMTK_MARK_RATE_MBPMS`, 1 MB/ms;
   quantum = debt ÷ (runway ÷ nursery), runway from the *live* heap limit) and
   hands it to core. Core now paces slices itself: an inflow floor plus a share
   of the backlog sized to finish inside a runway *frozen at InitialMark*, capped
   at the pause target from its own *measured* mark rate. The hint survives only
   as the extra time budget after the floor, and the debt estimate only as one
   half of the gate's "worth" test (the other half is the measured Full
   duration). Two mark-rate notions (assumed in the binding, measured in core)
   and two runway notions (live vs frozen) coexist. Recommendation: move the
   hint's remaining role into core (it has the measurements) and reduce the
   binding to requesting cycles.
2. **Cycle-start laws in the binding vs the trigger in core.** The binding decides
   *when* a major cycle starts (margin ×2.5 over the marked-live baseline,
   clamped by `MMTK_CONC_TRIGGER_PCT` of the heap; allocation cadence of
   2 × baseline; the mature-direct tick), while core's `SpaceOverheadTrigger`
   decides *how big the heap may be* and, since v6, also has a latency-aware
   start request. Both consult "live", now from the same marked-bytes source, so
   they agree, but the reviewer should know the start decision is split across
   `collection.rs` (binding) and `bactrian/global.rs` (core).
3. **Nursery sizing on both sides.** The binding installs `Bounded:2 MiB,16 MiB`
   and scales it per domain (`NURSERY_PER_DOMAIN`, `update_nursery_scale`); core's
   trigger clamps any nursery to a quarter of the heap and applies the scaled
   headroom. The result is consistent, but the effective nursery is the product
   of three rules in two repos.
4. **The same env knob read on both sides.** `MMTK_MEDIUM_NONMOVING` is read by
   the runtime (4 sites, `caml_mmtk_semantics`) and by core's Bactrian mutator
   (allocator mapping): both must agree or objects go to the wrong space.
   `MMTK_PAUSE_LOG`, `MMTK_VERBOSE`, `MMTK_HEAP_SIZE_MB` are read by both the
   runtime and the binding. `MMTK_PACE_DEBUG` prints from both the binding and
   core with the same `[pace]` prefix. Suggest one owner per knob (the binding
   reads it once and passes a value down / up) or at least a table listing the
   readers.
5. **Off-heap and LOS memory accounting.** The binding credits off-heap custom
   memory into the heap limit (`vm_live_bytes`, `OFFHEAP_BYTES_SINCE_FULL`) and
   the cadence budget is denominated in the post-full baseline to keep that
   credit from deferring fulls; core (August, a7b10f3d85) counts LOS pages toward
   mature pressure and returns large frees to the OS. Complementary, not
   duplicate, but they were designed in the same campaign and the PR description
   should present them together.
6. **Submodule bumps (21 commits).** Each core change appears in this PR only as
   a pointer bump. The reviewer of #23 sees none of the core content; make the PR
   description link the corresponding mmtk-core PR #1 commits, or squash the
   bumps.

### 4.7 Decision: what must change, and where

- **Must (both PRs): retire the binding's quantum-hint law (§4.1).** After honest
  pacing it is vestigial: core paces slices from a frozen runway and a measured
  rate; the hint only tops up the time budget and its debt estimate (live ÷ an
  assumed 1 MB/ms, ~5× off on eio/sedlex) is half of the gate's "worth" test.
  Leaving two laws in two repos is the thing a reviewer of either PR will trip
  on. Binding: drop `hint_mark_quantum` / `MMTK_MARK_RATE_MBPMS`, keep only the
  cycle request. Core: `set_mark_quantum_hint_ms` goes; the slice time budget
  falls back to `MMTK_MARK_SLICE_MS` after the floors; "worth" from the measured
  Full duration or marked bytes over the measured mark rate. ~60 lines, needs a
  re-measure of eio / ydump / sedlex.
- **Document, don't change now:** the cycle-start split (§4.2; core's
  latency-aware start fired once in the sedlex debug run and never on eio),
  nursery sizing in two repos (§4.3), knobs read on several sides (§4.4 — a
  table in the PR description), the off-heap/LOS pairing (§4.5), and the
  submodule bumps (§4.6 — link PR #1's commits).

### 4.8 Done (2026-09-23)

The must-fix (§4.7) is on both PRs: mmtk-core `0.32-ocaml` 22351d1644 (hint
law retired, Full cost predicted from measurements), 9372c33c01 (prediction
scaled by heap growth), abd1879f6f (mature-bytes floor); ocaml-mmtk
`shape/tweaks` 22ade70f2 (binding requests cycles only) with submodule bumps.
The PR's binding also gained the two August pacing commits it was missing
(d9816ef9d off-heap credit, e16d20e0a baseline-scaled cadence), so it now
matches the measured tree. Numbers (v7c): eio 155 s / 4.1 GB / 266 ms, ydump
71 s / 11.6 GB / 156 ms, sedlex 125 s / 8.7 GB / 123 ms, decompress 58 s /
1.0 GB / 7 ms; binarytrees unchanged. Details: `quick/sedlex/REPORT.md` §v7.

## 5. What is *not* in this PR but affects it

- mmtk-core PR #1 now includes the August trigger commits (032100ea2a,
  a7b10f3d85), the inflow floor and guards (557c0d77de), honest pacing
  (4660d08769) and four CI commits. The binding side of honest pacing is
  19ca2fe1c here (15 lines).
- The measured effect of the current head (macro benches, idle church, 1 GC
  worker): eio 13.1 → 3.6 GB RSS with worst pause 1.18 s → 0.48 s; ydump / sedlex
  / decompress hold RSS with worst pauses 184 / 177 / 15 ms; cost +24–29 % wall
  on the three promotion-heavy benches from 1.4–1.5× the GC time (more cycles at
  an honest 2.2 × live). Full tables: `quick/sedlex/REPORT.md`.

## 6. Suggested review order

1. `runtime/mmtk.c` (+406): allocation paths, TLAB refill, mature-direct tick,
   medium/LOS placement — the runtime contract with the collector.
2. `gc/mmtk/binding/src/collection.rs`: the pause protocol and the cycle-start
   laws (§4.1–4.2 above), with `MMTK_PACE_DEBUG` output from an eio run at hand.
3. `gc/mmtk/binding/src/api.rs`: nursery and heap-trigger defaults (§4.3).
4. `gc/mmtk/common` + `include`: slot/scanning helpers (the LTO rationale).
5. Docs last, after deciding §3.2–3.3.
