import sys, pathlib
root = pathlib.Path(sys.argv[1])
def patch(rel, old, new, n=1):
    p = root / rel; s = p.read_text(); c = s.count(old)
    if new in s: print("  already", rel); return
    assert c == n, f"{rel}: found {c} != {n} of {old[:70]!r}"
    p.write_text(s.replace(old, new)); print("  patched", rel)
MOD = "src/plan/concurrent/mod.rs"; CMW = "src/plan/concurrent/concurrent_marking_work.rs"
GL = "src/plan/concurrent/bactrian/global.rs"; GW = "src/plan/concurrent/bactrian/gc_work.rs"
# --- counters: SATB records turned into marking packets
patch(MOD, """    /// SATB old values enqueued by the barrier.
    pub static SATB_ENQ: AtomicUsize = AtomicUsize::new(0);
""", """    /// SATB old values enqueued by the barrier.
    pub static SATB_ENQ: AtomicUsize = AtomicUsize::new(0);
    /// SATB old values handed to a ConcurrentTraceObjects packet (ProcessModBufSATB ran).
    pub static SATB_RUN: AtomicUsize = AtomicUsize::new(0);
""")
patch(CMW, """            if nodes.is_empty() {
                return;
            }
""", """            if nodes.is_empty() {
                return;
            }
            crate::plan::concurrent::diag::SATB_RUN
                .fetch_add(nodes.len(), std::sync::atomic::Ordering::Relaxed);
""")
# --- plan state
patch(GL, """    pub(in crate::plan) enqueued_at_last_quantum: AtomicU64,
""", """    pub(in crate::plan) enqueued_at_last_quantum: AtomicU64,
    /// Mature reserved pages at this pause's prepare(); the Release-stage
    /// quanta read the pause's promotion as (mature now − this).
    mature_at_prepare: AtomicU64,
    /// EWMA (alpha 1/4) of pages promoted per nursery pause, sampled in the
    /// quanta: the projection guards' "minors available" = runway / this.
    promotion_ewma_pages: AtomicU64,
    /// EWMA (alpha 1/4) of a budgeted mark quantum's net progress in objects
    /// (traced − inflow; ≥ 0 under the inflow floor). 0 = no sample yet.
    mark_net_ewma: AtomicU64,
    /// Budgeted mark quanta run in the current cycle (warm-up before the
    /// projection guard judges).
    mark_slices_this_cycle: AtomicU64,
    /// (SATB_ENQ − SATB_RUN) at InitialMark: records made outside a cycle are
    /// dropped unexecuted, so the in-cycle backlog is measured from here.
    satb_drift_at_cycle_start: AtomicU64,
    /// EWMA (alpha 1/4, ×256 fixed point) of sweep packets completed per
    /// budgeted sweep quantum, and the budgeted sweep quanta run since
    /// FinalMark (warm-up).
    sweep_packets_ewma_x256: AtomicU64,
    sweep_slices_this_cycle: AtomicU64,
    /// Set by the projection guards (see BactrianMarkQuantum /
    /// BactrianSweepQuantum): the next mark / sweep quantum runs unbudgeted —
    /// drain to completion in one pause — because at the measured net rate the
    /// work would not finish before promotion consumed the runway.
    escalate_mark: AtomicBool,
    escalate_sweep: AtomicBool,
""")
patch(GL, """            enqueued_at_last_quantum: AtomicU64::new(0),
""", """            enqueued_at_last_quantum: AtomicU64::new(0),
            mature_at_prepare: AtomicU64::new(0),
            promotion_ewma_pages: AtomicU64::new(0),
            mark_net_ewma: AtomicU64::new(0),
            mark_slices_this_cycle: AtomicU64::new(0),
            satb_drift_at_cycle_start: AtomicU64::new(0),
            sweep_packets_ewma_x256: AtomicU64::new(0),
            sweep_slices_this_cycle: AtomicU64::new(0),
            escalate_mark: AtomicBool::new(false),
            escalate_sweep: AtomicBool::new(false),
""")
patch(GL, """        self.pause_start_nanos.store(now_nanos(), Ordering::Relaxed);
""", """        self.pause_start_nanos.store(now_nanos(), Ordering::Relaxed);
        self.mature_at_prepare
            .store(self.get_mature_reserved_pages() as u64, Ordering::Relaxed);
""")
# cycle-start resets (end of InitialMark)
patch(GL, """                self.enqueued_at_last_quantum.store(
                    (crate::plan::concurrent::diag::ENQUEUED.load(Ordering::Relaxed)
                        + crate::plan::concurrent::diag::SATB_ENQ.load(Ordering::Relaxed))
                        as u64,
                    Ordering::Relaxed,
                );
                debug_assert!(self.concurrent_marking_in_progress());""",
"""                self.enqueued_at_last_quantum.store(
                    (crate::plan::concurrent::diag::ENQUEUED.load(Ordering::Relaxed)
                        + crate::plan::concurrent::diag::SATB_ENQ.load(Ordering::Relaxed))
                        as u64,
                    Ordering::Relaxed,
                );
                self.mark_net_ewma.store(0, Ordering::Relaxed);
                self.mark_slices_this_cycle.store(0, Ordering::Relaxed);
                self.satb_drift_at_cycle_start.store(
                    crate::plan::concurrent::diag::SATB_ENQ
                        .load(Ordering::Relaxed)
                        .saturating_sub(crate::plan::concurrent::diag::SATB_RUN.load(Ordering::Relaxed))
                        as u64,
                    Ordering::Relaxed,
                );
                debug_assert!(self.concurrent_marking_in_progress());""")
# sweep-start resets (end of FinalMark)
patch(GL, """            Pause::FinalMark => {
                // End the MARKING half of the cycle, but under INCREMENTAL""",
"""            Pause::FinalMark => {
                self.sweep_packets_ewma_x256.store(0, Ordering::Relaxed);
                self.sweep_slices_this_cycle.store(0, Ordering::Relaxed);
                // End the MARKING half of the cycle, but under INCREMENTAL""")
# escalation consumers
patch(GL, """                            let w = if emergency {
                                BactrianMarkQuantum::unbudgeted(self)""",
"""                            let w = if emergency
                                || self.escalate_mark.swap(false, Ordering::SeqCst)
                            {
                                BactrianMarkQuantum::unbudgeted(self)""")
patch(GL, """                        let w = if emergency {
                            BactrianSweepQuantum::unbudgeted(self)""",
"""                        let w = if emergency
                            || self.escalate_sweep.swap(false, Ordering::SeqCst)
                        {
                            BactrianSweepQuantum::unbudgeted(self)""")
# helpers
patch(GL, """    pub(super) fn sweep_queue_is_empty(&self) -> bool {
        self.parked_sweep.is_empty()
    }
""", """    pub(super) fn sweep_queue_is_empty(&self) -> bool {
        self.parked_sweep.is_empty()
    }

    /// Parked sweep packets still to run (one chunk each).
    pub(super) fn sweep_packets_remaining(&self) -> usize {
        self.parked_sweep.len()
    }

    /// Pages between the trigger's current heap size and mature: what
    /// promotion can consume before the heap is full.
    pub(super) fn runway_pages(&self) -> usize {
        self.gen
            .common
            .base
            .gc_trigger
            .policy
            .get_current_heap_size_in_pages()
            .saturating_sub(self.get_mature_reserved_pages())
    }

    /// Objects still to trace in this cycle: parked-but-unexecuted marking
    /// packets (ENQUEUED − TRACED) plus SATB records not yet turned into
    /// packets (SATB_ENQ − SATB_RUN, net of the pre-cycle drift).
    pub(super) fn mark_backlog_objects(&self) -> usize {
        use crate::plan::concurrent::diag::{ENQUEUED, SATB_ENQ, SATB_RUN, TRACED};
        let parked = ENQUEUED
            .load(Ordering::Relaxed)
            .saturating_sub(TRACED.load(Ordering::Relaxed));
        let satb = SATB_ENQ
            .load(Ordering::Relaxed)
            .saturating_sub(SATB_RUN.load(Ordering::Relaxed))
            .saturating_sub(self.satb_drift_at_cycle_start.load(Ordering::Relaxed) as usize);
        parked + satb
    }

    /// Projection-guard bookkeeping shared by both quanta (Release stage:
    /// this pause's promotions are in, nothing swept yet): fold this pause's
    /// promotion into the EWMA and return (promotion_ewma_pages, runway_pages).
    pub(super) fn sample_promotion(&self) -> (u64, u64) {
        let now = self.get_mature_reserved_pages() as u64;
        let promoted = now.saturating_sub(self.mature_at_prepare.load(Ordering::Relaxed));
        let prev = self.promotion_ewma_pages.load(Ordering::Relaxed);
        let next = if prev == 0 { promoted } else { prev - prev / 4 + promoted / 4 };
        self.promotion_ewma_pages.store(next, Ordering::Relaxed);
        (next, self.runway_pages() as u64)
    }

    pub(super) fn note_mark_slice(&self, net: u64) -> (u64, u64) {
        let prev = self.mark_net_ewma.load(Ordering::Relaxed);
        let next = if prev == 0 { net } else { prev - prev / 4 + net / 4 };
        self.mark_net_ewma.store(next, Ordering::Relaxed);
        (next, self.mark_slices_this_cycle.fetch_add(1, Ordering::Relaxed) + 1)
    }

    pub(super) fn note_sweep_slice(&self, packets: u64) -> (u64, u64) {
        let prev = self.sweep_packets_ewma_x256.load(Ordering::Relaxed);
        let next = if prev == 0 { packets * 256 } else { prev - prev / 4 + packets * 64 };
        self.sweep_packets_ewma_x256.store(next, Ordering::Relaxed);
        (next, self.sweep_slices_this_cycle.fetch_add(1, Ordering::Relaxed) + 1)
    }

    pub(super) fn request_escalate_mark(&self) {
        self.escalate_mark.store(true, Ordering::SeqCst);
    }

    pub(super) fn request_escalate_sweep(&self) {
        self.escalate_sweep.store(true, Ordering::SeqCst);
    }
""")
# --- mark quantum: projection guard
patch(GW, """        if let Some(q) = quota {
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
""", """        if let Some(q) = quota {
            // Projection guard: at the measured net rate (objects of backlog
            // retired per slice, EWMA), does the backlog finish before
            // promotion (pages per minor, EWMA) consumes the runway? If not,
            // the next quantum runs unbudgeted — drain in one pause, FinalMark
            // next — the legal mid-cycle equivalent of giving up on slicing (a
            // Full cannot start with a cycle in flight). A short warm-up keeps
            // a bursty first few slices from firing it. A queue that is not
            // shrinking at all is the infinite case of the same test.
            let traced = TRACED.load(Relaxed) - traced_at_start;
            let net = traced.saturating_sub(q) as u64;
            let (net_ewma, slices) = self.plan.note_mark_slice(net);
            let (promo, runway) = self.plan.sample_promotion();
            let backlog = self.plan.mark_backlog_objects();
            let drained = self.plan.marking_queue_drained();
            let need = if net_ewma == 0 { f64::INFINITY } else { backlog as f64 / net_ewma as f64 };
            let avail = if promo == 0 { f64::INFINITY } else { runway as f64 / promo as f64 };
            let escalate = !drained && slices >= 4 && need > avail;
            if escalate {
                self.plan.request_escalate_mark();
            }
            if std::env::var_os("MMTK_PACE_DEBUG").is_some() {
                eprintln!(
                    "[pace] quantum: budget={:.1}ms quota={} traced={} packets={} took={:.1}ms drained={} | guard: backlog={} net={}/slice promo={}p runway={}MB need={:.0} avail={:.0} slices={}{}",
                    self.budget.map(|b| b.as_secs_f64() * 1e3).unwrap_or(0.0),
                    q,
                    traced,
                    packets,
                    started.elapsed().as_secs_f64() * 1e3,
                    drained,
                    backlog,
                    net_ewma,
                    promo,
                    runway * 4096 / (1 << 20),
                    need,
                    avail,
                    slices,
                    if escalate { " -> ESCALATE" } else { "" }
                );
            }
        }
""")
# --- sweep quantum: projection guard
patch(GW, """        let deadline = self.budget.map(|b| std::time::Instant::now() + b);
        let mut packets = 0usize;
        loop {
            let Some(mut w) = self.plan.pop_sweep_packet() else {""",
"""        let deadline = self.budget.map(|b| std::time::Instant::now() + b);
        // Sample this pause's promotion BEFORE sweeping (the sweep frees
        // mature pages, which would hide it) — see sample_promotion.
        let promo_runway = self.budget.map(|_| self.plan.sample_promotion());
        let started = std::time::Instant::now();
        let mut packets = 0usize;
        loop {
            let Some(mut w) = self.plan.pop_sweep_packet() else {""")
patch(GW, """        probe!(mmtk, bactrian_sweep_quantum, packets);
""", """        if let Some((promo, runway)) = promo_runway {
            // Projection guard for the sweep: a pending cycle request waits on
            // this drain, so at the measured packets-per-slice rate the
            // remaining chunks must be swept before promotion consumes the
            // runway; otherwise the next sweep quantum runs unbudgeted.
            let (ewma_x256, slices) = self.plan.note_sweep_slice(packets as u64);
            let remaining = self.plan.sweep_packets_remaining();
            let need = if ewma_x256 == 0 {
                f64::INFINITY
            } else {
                remaining as f64 * 256.0 / ewma_x256 as f64
            };
            let avail = if promo == 0 { f64::INFINITY } else { runway as f64 / promo as f64 };
            let escalate = remaining > 0 && slices >= 2 && need > avail;
            if escalate {
                self.plan.request_escalate_sweep();
            }
            if std::env::var_os("MMTK_PACE_DEBUG").is_some() {
                eprintln!(
                    "[pace] sweep quantum: packets={} took={:.1}ms remaining={} rate={:.1}/slice promo={}p runway={}MB need={:.0} avail={:.0} slices={}{}",
                    packets,
                    started.elapsed().as_secs_f64() * 1e3,
                    remaining,
                    ewma_x256 as f64 / 256.0,
                    promo,
                    runway * 4096 / (1 << 20),
                    need,
                    avail,
                    slices,
                    if escalate { " -> ESCALATE" } else { "" }
                );
            }
        }
        probe!(mmtk, bactrian_sweep_quantum, packets);
""")
print("OK", root)
