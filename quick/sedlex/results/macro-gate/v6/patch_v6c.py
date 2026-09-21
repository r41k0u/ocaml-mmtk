import sys, pathlib
root = pathlib.Path(sys.argv[1]); GL = root/"src/plan/concurrent/bactrian/global.rs"; s = GL.read_text()
def rep(old, new):
    global s
    if new in s: print("  already"); return
    assert s.count(old) == 1, (s.count(old), old[:60]); s = s.replace(old, new); print("  patched")
rep("""    /// now_nanos() at the current pause's prepare(), for the EWMA above.
    pause_start_nanos: AtomicU64,
""", """    /// now_nanos() at the current pause's prepare(), for the EWMA above.
    pause_start_nanos: AtomicU64,
    /// EWMA (alpha 1/4) of monolithic Full pause wall time in nanoseconds.
    /// The slicing gate's "worth" test uses it beside the live/mark-rate
    /// estimate: that estimate is live-only at an assumed rate, while a Full
    /// also sweeps everything reserved and pays fixed per-pause work (eio:
    /// estimate 80-180 ms, measured Fulls 0.4-1.8 s). 0 = no Full yet.
    full_pause_ewma_nanos: AtomicU64,
""")
rep("""            pause_start_nanos: AtomicU64::new(0),
""", """            pause_start_nanos: AtomicU64::new(0),
            full_pause_ewma_nanos: AtomicU64::new(0),
""")
rep("""        if matches!(pause, Pause::Nursery) {
            let start = self.pause_start_nanos.load(Ordering::Relaxed);
            if start != 0 {
                let dur = now_nanos().saturating_sub(start);
                let prev = self.nursery_pause_ewma_nanos.load(Ordering::Relaxed);
                let next = if prev == 0 { dur } else { prev - prev / 4 + dur / 4 };
                self.nursery_pause_ewma_nanos.store(next, Ordering::Relaxed);
            }
        }
""", """        if matches!(pause, Pause::Nursery | Pause::Full) {
            let start = self.pause_start_nanos.load(Ordering::Relaxed);
            if start != 0 {
                let dur = now_nanos().saturating_sub(start);
                let slot = if matches!(pause, Pause::Nursery) {
                    &self.nursery_pause_ewma_nanos
                } else {
                    &self.full_pause_ewma_nanos
                };
                let prev = slot.load(Ordering::Relaxed);
                let next = if prev == 0 { dur } else { prev - prev / 4 + dur / 4 };
                slot.store(next, Ordering::Relaxed);
            }
        }
""")
rep("""                    let worth = debt_ms > slice_worth_ms();
""", """                    let full_ms =
                        self.full_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                    // Worth slicing if EITHER the estimate or the measured
                    // Full duration exceeds the bar.
                    let worth = debt_ms > slice_worth_ms() || full_ms > slice_worth_ms();
""")
rep("""                            "[pace] slice gate: debt={:.0}ms quantum={:.1}ms minor_ewma={:.1}ms tick={} worth={} feasible={} -> {}",
                            debt_ms, quantum_ms, minor_ms, tick_origin, worth, feasible,""",
"""                            "[pace] slice gate: debt={:.0}ms full_ewma={:.0}ms quantum={:.1}ms minor_ewma={:.1}ms tick={} worth={} feasible={} -> {}",
                            debt_ms, full_ms, quantum_ms, minor_ms, tick_origin, worth, feasible,""")
GL.write_text(s); print("v6c OK", root)
