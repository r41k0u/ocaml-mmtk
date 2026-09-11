import sys, pathlib
root = pathlib.Path(sys.argv[1])
def patch(rel, old, new, n=1):
    p = root / rel; s = p.read_text(); c = s.count(old)
    if new in s: print("  already", rel); return
    assert c == n, f"{rel}: found {c} != {n} of {old[:60]!r}"
    p.write_text(s.replace(old, new)); print("  patched", rel)
GL = "src/plan/concurrent/bactrian/global.rs"; GW = "src/plan/concurrent/bactrian/gc_work.rs"
patch(GL, """    /// diag::ENQUEUED when the previous mark quantum finished (or when
    /// InitialMark ended). Everything handed to marking packets since then —
    /// SATB old values parked by the barrier between pauses and at mutator
    /// flush, plus whatever the nursery closure seeds — is the inflow the next
    /// quantum must at least retire (its work floor; see BactrianMarkQuantum).
    /// A quantum's own child packets are excluded: it snapshots after its drain.
    pub(in crate::plan) enqueued_at_last_quantum: AtomicU64,
""", """    /// Inflow mark (diag::ENQUEUED + diag::SATB_ENQ) when the previous mark
    /// quantum finished (or when InitialMark ended). Everything since then —
    /// SATB old values the barrier recorded between pauses (counted at
    /// enqueue time: their ProcessModBufSATB packets only reach ENQUEUED when
    /// they run inside a quantum), plus whatever the nursery closure seeds —
    /// is the inflow the next quantum must retire before its time budget
    /// starts (see BactrianMarkQuantum). A quantum's own child packets are
    /// excluded: it snapshots after its drain.
    pub(in crate::plan) enqueued_at_last_quantum: AtomicU64,
""")
patch(GL, """                self.enqueued_at_last_quantum.store(
                    crate::plan::concurrent::diag::ENQUEUED.load(Ordering::Relaxed) as u64,
                    Ordering::Relaxed,
                );
                debug_assert!(self.concurrent_marking_in_progress());""",
"""                self.enqueued_at_last_quantum.store(
                    (crate::plan::concurrent::diag::ENQUEUED.load(Ordering::Relaxed)
                        + crate::plan::concurrent::diag::SATB_ENQ.load(Ordering::Relaxed))
                        as u64,
                    Ordering::Relaxed,
                );
                debug_assert!(self.concurrent_marking_in_progress());""")
patch(GW, """        use crate::plan::concurrent::diag::{ENQUEUED, TRACED};
        use std::sync::atomic::Ordering::Relaxed;
        let quota = self.budget.map(|_| {
            ENQUEUED
                .load(Relaxed)
                .saturating_sub(self.plan.enqueued_at_last_quantum.load(Relaxed) as usize)
        });
""", """        use crate::plan::concurrent::diag::{ENQUEUED, SATB_ENQ, TRACED};
        use std::sync::atomic::Ordering::Relaxed;
        // SATB old values are counted at enqueue time (SATB_ENQ, mutator side):
        // their ProcessModBufSATB packets only feed ENQUEUED when they execute
        // inside a quantum, which is after this quota is read.
        let inflow_mark = || ENQUEUED.load(Relaxed) + SATB_ENQ.load(Relaxed);
        let quota = self.budget.map(|_| {
            inflow_mark().saturating_sub(self.plan.enqueued_at_last_quantum.load(Relaxed) as usize)
        });
""")
patch(GW, """        self.plan
            .enqueued_at_last_quantum
            .store(ENQUEUED.load(Relaxed) as u64, Relaxed);
""", """        self.plan
            .enqueued_at_last_quantum
            .store(inflow_mark() as u64, Relaxed);
""")
print("OK", root)
