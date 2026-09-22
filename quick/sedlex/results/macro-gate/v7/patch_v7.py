import sys, pathlib
core = pathlib.Path(sys.argv[1]); bind = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
def patch(path, old, new, n=1):
    s = path.read_text()
    if new and new in s and s.count(old) == 0: print("  already", path.name); return
    assert s.count(old) == n, (path.name, s.count(old), old[:60]); path.write_text(s.replace(old, new)); print("  patched", path.name)
CG = core/"src/plan/concurrent/global.rs"; GL = core/"src/plan/concurrent/bactrian/global.rs"; GW = core/"src/plan/concurrent/bactrian/gc_work.rs"
# --- trait
patch(CG, """    /// `tick_origin` says WHICH pacing site fired: `false` = the post-minor
    /// path (pause cadence = minors — a big-nursery config's minors are
    /// promotion-bound and dwarf any quantum, so slicing is pointless there:
    /// the plan's feasibility gate degrades the cycle to a monolithic Full);
    /// `true` = the mature-direct allocation tick (pause cadence = tick
    /// batches — near-empty nursery collections that stay small at ANY
    /// nursery cap, so the nursery gate must not apply; fragmed flipped from
    /// cycles to 11 monolithic Fulls, D1 3.4→5.0×, when it did).
    fn set_mark_quantum_hint_ms(&self, _ms: f64, _debt_ms: f64, _tick_origin: bool) {}
""", """    /// Record WHICH pacing site fired the cycle being requested: `false` =
    /// the post-minor path, `true` = the mature-direct allocation tick (pause
    /// cadence = tick batches — near-empty nursery collections that stay
    /// small at any nursery cap, so the slicing gate must not degrade such a
    /// cycle to a monolithic Full; fragmed flipped from cycles to 11 Fulls,
    /// D1 3.4→5.0×, when it did). Slice sizing itself is the plan's: it
    /// paces from the runway frozen at InitialMark and its measured mark
    /// rate, so the binding passes no quantum or debt estimate.
    fn set_cycle_tick_origin(&self, _tick_origin: bool) {}
""")
# --- Bactrian state
patch(GL, """    /// Per-pause mark-quantum budget hint in nanoseconds, set by the
    /// binding's pacing at cycle-trigger time (ConcurrentPlan::
    /// set_mark_quantum_hint_ms — stock's slice-sizing law: mark debt over
    /// runway pauses). 0 = use the static MMTK_MARK_SLICE_MS budget.
    pub(in crate::plan) mark_quantum_hint_nanos: AtomicU64,
    /// Did the mature-direct allocation TICK fire the pending cycle (vs the
    /// post-minor path)? Tick-paced cycles progress in near-empty nursery
    /// pauses that stay small at any nursery cap, so the feasibility
    /// escape's nursery gate must not degrade them to monolithic Fulls.
    cycle_tick_origin: AtomicBool,
    /// Estimated monolithic-Full mark time in nanoseconds (live / mark-rate),
    /// stored beside the quantum hint; the slicing gate slices only when this
    /// exceeds MMTK_SLICE_WORTH_MS (a short Full is not worth slicing).
    mark_debt_nanos: AtomicU64,
""", """    /// Did the mature-direct allocation TICK fire the pending cycle (vs the
    /// post-minor path)? Tick-paced cycles progress in near-empty nursery
    /// pauses that stay small at any nursery cap, so the slicing gate must
    /// not degrade them to monolithic Fulls.
    cycle_tick_origin: AtomicBool,
""")
patch(GL, """            mark_quantum_hint_nanos: AtomicU64::new(0),
            cycle_tick_origin: AtomicBool::new(false),
            mark_debt_nanos: AtomicU64::new(0),
""", """            cycle_tick_origin: AtomicBool::new(false),
""")
patch(GL, """    fn set_mark_quantum_hint_ms(&self, ms: f64, debt_ms: f64, tick_origin: bool) {
        let ns = (ms.max(0.0) * 1e6) as u64;
        self.mark_quantum_hint_nanos.store(ns, Ordering::Relaxed);
        // debt_ms = live / mark-rate = the estimated monolithic-Full mark time,
        // read by the slicing gate as the "is a Full too long?" quantity.
        self.mark_debt_nanos
            .store((debt_ms.max(0.0) * 1e6) as u64, Ordering::Relaxed);
        self.cycle_tick_origin.store(tick_origin, Ordering::Relaxed);
    }
""", """    fn set_cycle_tick_origin(&self, tick_origin: bool) {
        self.cycle_tick_origin.store(tick_origin, Ordering::Relaxed);
    }
""")
# --- gate: worth from measurements, no feasibility test, no binding estimate
patch(GL, """                    // Full. (Replaces the old nursery-size + max-quantum gates.)
                    //  WORTH: the monolithic Full would be too long. debt_ms
                    //   (live / mark-rate) is its estimated mark time; under
                    //   MMTK_SLICE_WORTH_MS the Full is short, so slicing buys no
                    //   worst-case-pause win and only costs throughput
                    //   (bt-def@192M: 2663ms Full vs 3181ms sliced, ~103-138ms
                    //   max pause either way) — don't slice.
                    //  FEASIBLE: the sliced pause fits the target. Estimate is
                    //   the recent nursery-pause EWMA + this cycle's quantum;
                    //   above MMTK_SLICE_MAX_PAUSE_MS slicing cannot keep pauses
                    //   small (the intent of the old nursery/quantum gates).
                    // Tick-origin cycles (mature-direct pacing) run in near-empty
                    // minors and always slice.
                    let tick_origin = self.cycle_tick_origin.load(Ordering::Relaxed);
                    let debt_ms =
                        self.mark_debt_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                    let quantum_ms =
                        self.mark_quantum_hint_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                    let minor_ms =
                        self.nursery_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                    let full_ms =
                        self.full_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                    // Worth slicing if EITHER the estimate or the measured
                    // Full duration exceeds the bar.
                    let worth = debt_ms > slice_worth_ms() || full_ms > slice_worth_ms();
                    // With runway-paced, target-capped slices the sliced pause is
                    // bounded by construction; what slicing costs when the runway
                    // is short is bounded heap overshoot, not pause time, while a
                    // monolithic Full of a large live set costs seconds (ydump:
                    // 14.5 s). The binding's quantum hint (debt over the live
                    // limit's runway) is only informational now. Slice whenever
                    // it is worth it; MMTK_SLICE_FEASIBLE=1 restores the old test.
                    let feasible = if std::env::var_os("MMTK_SLICE_FEASIBLE").is_some() {
                        minor_ms + quantum_ms <= slice_max_pause_ms()
                    } else {
                        true
                    };
                    // true => monolithic Full instead of slicing.
                    let monolithic = !tick_origin && (!worth || !feasible);
                    if std::env::var_os("MMTK_PACE_DEBUG").is_some() {
                        eprintln!(
                            "[pace] slice gate: debt={:.0}ms full_ewma={:.0}ms quantum={:.1}ms minor_ewma={:.1}ms tick={} worth={} feasible={} -> {}",
                            debt_ms, full_ms, quantum_ms, minor_ms, tick_origin, worth, feasible,
                            if monolithic { "Full" } else { "sliced" }
                        );
                    }
                    monolithic
""", """                    // Full. Slice iff the monolithic Full would be too long:
                    // under MMTK_SLICE_WORTH_MS a Full is short, so slicing buys
                    // no worst-case-pause win and only costs throughput
                    // (bt-def@192M: 2663ms Full vs 3181ms sliced, ~103-138ms max
                    // pause either way). With runway-paced, target-capped slices
                    // the sliced pause is bounded by construction, so there is no
                    // feasibility test: what slicing costs when the runway is
                    // short is bounded heap overshoot, while a monolithic Full of
                    // a large live set costs seconds (ydump: 14.5 s).
                    // The Full's cost is predicted from measurements, not from
                    // a binding-side estimate: the EWMA of Fulls already run, or
                    // the last sliced cycle's live object count at the measured
                    // mark rate; before either exists, mature bytes at an
                    // assumed 1 MB/ms (a bootstrap only). Tick-origin cycles
                    // (mature-direct pacing) run in near-empty minors and
                    // always slice.
                    let tick_origin = self.cycle_tick_origin.load(Ordering::Relaxed);
                    let full_ms =
                        self.full_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                    let objs = self.last_cycle_traced_objs.load(Ordering::Relaxed);
                    let rate = self.mark_rate_objs_per_ms_x256.load(Ordering::Relaxed);
                    let pred_ms = if objs > 0 && rate > 0 {
                        objs as f64 * 256.0 / rate as f64
                    } else {
                        (self.get_mature_reserved_pages() * crate::util::constants::BYTES_IN_PAGE)
                            as f64
                            / 1048576.0
                    };
                    let worth = full_ms > slice_worth_ms() || pred_ms > slice_worth_ms();
                    // true => monolithic Full instead of slicing.
                    let monolithic = !tick_origin && !worth;
                    if std::env::var_os("MMTK_PACE_DEBUG").is_some() {
                        eprintln!(
                            "[pace] slice gate: full_ewma={:.0}ms predicted={:.0}ms tick={} worth={} -> {}",
                            full_ms,
                            pred_ms,
                            tick_origin,
                            worth,
                            if monolithic { "Full" } else { "sliced" }
                        );
                    }
                    monolithic
""")
# --- quantum time budget: the static slice budget after the floors
patch(GW, """    pub(in crate::plan) fn budgeted(plan: &'static Bactrian<VM>) -> Self {
        // Per-cycle hint (ConcurrentPlan::set_mark_quantum_hint_ms — the
        // binding's slice-sizing law: mark debt spread over the runway's
        // pauses) overrides the static budget; 0 = never hinted.
        let hint = plan
            .mark_quantum_hint_nanos
            .load(std::sync::atomic::Ordering::Relaxed);
        let budget = if hint > 0 {
            std::time::Duration::from_nanos(hint)
        } else {
            mark_slice_budget()
        };
        Self {
            plan,
            budget: Some(budget),
        }
    }
""", """    pub(in crate::plan) fn budgeted(plan: &'static Bactrian<VM>) -> Self {
        // The time budget only tops up the work floors (inflow, then the
        // runway share); MMTK_MARK_SLICE_MS, default 2 ms.
        Self {
            plan,
            budget: Some(mark_slice_budget()),
        }
    }
""")
print("core OK")
if bind:
    B = bind/"src/collection.rs"
    patch(B, """/// Assumed mark throughput for the quantum-sizing law, MB per ms
/// (MMTK_MARK_RATE_MBPMS overrides; ~1.0 measured on the Skylake bench
/// host: a 140MB live set monolithically marks in ~138ms).
fn mark_rate_bytes_per_ms() -> f64 {
    static V: std::sync::OnceLock<f64> = std::sync::OnceLock::new();
    *V.get_or_init(|| {
        std::env::var("MMTK_MARK_RATE_MBPMS")
            .ok()
            .and_then(|v| v.parse::<f64>().ok())
            .filter(|r| *r > 0.0)
            .unwrap_or(1.0)
            * 1048576.0
    })
}

""", "")
    s = B.read_text(); a = s.index("fn hint_mark_quantum(baseline_pages: usize, mature_pages: usize, tick_origin: bool) {"); b = s.index("\n}\n", a) + 3
    # include the doc comment lines immediately above the fn
    doc_start = a
    while True:
        prev = s.rfind("\n", 0, doc_start - 1) + 1
        line = s[prev:doc_start]
        if line.startswith("///"): doc_start = prev
        else: break
    new_fn = """/// Tell the plan which pacing site fired the cycle just requested (the
/// mature-direct tick vs the post-minor path); it decides slicing vs a
/// monolithic Full. Slice sizing is the plan's own (runway frozen at
/// InitialMark, measured mark rate), so no quantum or debt estimate is passed.
fn note_cycle_origin(tick_origin: bool) {
    if let Some(c) = crate::mmtk().get_plan().concurrent() {
        c.set_cycle_tick_origin(tick_origin);
    }
}
"""
    s = s[:doc_start] + new_fn + s[b:]; B.write_text(s); print("  replaced hint_mark_quantum")
    patch(B, "        hint_mark_quantum(baseline, mature, true);\n", "        note_cycle_origin(true);\n")
    patch(B, "                    hint_mark_quantum(baseline, mature, false);\n", "                    note_cycle_origin(false);\n")
    print("binding OK")
