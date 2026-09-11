import sys, pathlib
root = pathlib.Path(sys.argv[1])
def patch(rel, old, new, n=1):
    p = root / rel; s = p.read_text(); c = s.count(old)
    if new in s: print("  already", rel); return
    assert c == n, f"{rel}: found {c} != {n} of {old[:60]!r}"
    p.write_text(s.replace(old, new)); print("  patched", rel)
GL = "src/plan/concurrent/bactrian/global.rs"; GW = "src/plan/concurrent/bactrian/gc_work.rs"
patch(GL, """    /// now_nanos() at the current pause's prepare(), for the EWMA above.
    pause_start_nanos: AtomicU64,
""", """    /// now_nanos() at the current pause's prepare(), for the EWMA above.
    pause_start_nanos: AtomicU64,
    /// diag::ENQUEUED when the previous mark quantum finished (or when
    /// InitialMark ended). Everything handed to marking packets since then —
    /// SATB old values parked by the barrier between pauses and at mutator
    /// flush, plus whatever the nursery closure seeds — is the inflow the next
    /// quantum must at least retire (its work floor; see BactrianMarkQuantum).
    /// A quantum's own child packets are excluded: it snapshots after its drain.
    pub(in crate::plan) enqueued_at_last_quantum: AtomicU64,
""")
patch(GL, """            pause_start_nanos: AtomicU64::new(0),
""", """            pause_start_nanos: AtomicU64::new(0),
            enqueued_at_last_quantum: AtomicU64::new(0),
""")
# InitialMark's own seeds are the cycle's initial debt, not inflow: snapshot after it.
patch(GL, """            Pause::InitialMark => {
                // Marking state was already armed in prepare() (this pause's own
                // promotions must be born live); nothing further to do here.
                debug_assert!(self.concurrent_marking_in_progress());
            }""",
"""            Pause::InitialMark => {
                // Marking state was already armed in prepare() (this pause's own
                // promotions must be born live). The seeds InitialMark enqueued
                // are the cycle's initial debt, not inflow: start the quanta's
                // inflow window here.
                self.enqueued_at_last_quantum.store(
                    crate::plan::concurrent::diag::ENQUEUED.load(Ordering::Relaxed) as u64,
                    Ordering::Relaxed,
                );
                debug_assert!(self.concurrent_marking_in_progress());
            }""")
patch(GW, """        let deadline = self.budget.map(|b| std::time::Instant::now() + b);
        let mut packets = 0usize;
        // Run the drain under full-heap LOS semantics (mid-cycle marking must
        // mark mature LOS objects even when the enclosing pause latched
        // nursery semantics); restore the previous mode after.
        let was_full = mmtk
            .get_plan()
            .common()
            .los
            .set_marking_full_semantics(true);
        while let Some(mut w) = self.plan.pop_marking_packet() {
            w.do_work(worker, mmtk);
            packets += 1;
            if let Some(d) = deadline {
                if std::time::Instant::now() >= d {
                    break;
                }
            }
        }
        mmtk.get_plan()
            .common()
            .los
            .set_marking_full_semantics(was_full);
""", """        let deadline = self.budget.map(|b| std::time::Instant::now() + b);
        // Work floor (budgeted quanta only): drain at least as many objects as
        // were handed to marking packets since the previous quantum finished —
        // SATB old values the barrier parked between pauses and at mutator
        // flush, plus the nursery closure's seeds. The time budget alone is a
        // rate guess (debt over runway pauses at an assumed mark rate,
        // re-derived every minor against a heap that grows while the cycle is
        // open); if the inflow outruns it the parked queue only grows and the
        // cycle never reaches FinalMark. With the floor a quantum always
        // retires its own inflow, and the time budget works the original
        // debt on top. The quantum's own child packets are not inflow: the
        // snapshot is taken after the drain.
        use crate::plan::concurrent::diag::{ENQUEUED, TRACED};
        use std::sync::atomic::Ordering::Relaxed;
        let quota = self.budget.map(|_| {
            ENQUEUED
                .load(Relaxed)
                .saturating_sub(self.plan.enqueued_at_last_quantum.load(Relaxed) as usize)
        });
        let traced_at_start = TRACED.load(Relaxed);
        let started = std::time::Instant::now();
        let mut packets = 0usize;
        // Run the drain under full-heap LOS semantics (mid-cycle marking must
        // mark mature LOS objects even when the enclosing pause latched
        // nursery semantics); restore the previous mode after.
        let was_full = mmtk
            .get_plan()
            .common()
            .los
            .set_marking_full_semantics(true);
        while let Some(mut w) = self.plan.pop_marking_packet() {
            w.do_work(worker, mmtk);
            packets += 1;
            if let Some(d) = deadline {
                if std::time::Instant::now() >= d
                    && TRACED.load(Relaxed) - traced_at_start >= quota.unwrap_or(0)
                {
                    break;
                }
            }
        }
        mmtk.get_plan()
            .common()
            .los
            .set_marking_full_semantics(was_full);
        self.plan
            .enqueued_at_last_quantum
            .store(ENQUEUED.load(Relaxed) as u64, Relaxed);
        if let Some(q) = quota {
            if std::env::var_os("MMTK_PACE_DEBUG").is_some() {
                eprintln!(
                    "[pace] quantum: budget={:.1}ms quota={} traced={} packets={} took={:.1}ms drained={}",
                    self.budget.map(|b| b.as_secs_f64() * 1e3).unwrap_or(0.0),
                    q,
                    TRACED.load(Relaxed) - traced_at_start,
                    packets,
                    started.elapsed().as_secs_f64() * 1e3,
                    self.plan.marking_queue_drained()
                );
            }
        }
""")
print("OK", root)
