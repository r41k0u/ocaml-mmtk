import sys, pathlib
root = pathlib.Path(sys.argv[1]); bind = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
def patch(path, old, new, n=1):
    s = path.read_text(); c = s.count(old)
    if new in s: print("  already", path.name); return
    assert c == n, f"{path}: found {c} != {n} of {old[:70]!r}"
    path.write_text(s.replace(old, new)); print("  patched", path.name)
MOD = root/"src/plan/concurrent/mod.rs"; CMW = root/"src/plan/concurrent/concurrent_marking_work.rs"; CG = root/"src/plan/concurrent/global.rs"
GL = root/"src/plan/concurrent/bactrian/global.rs"; GW = root/"src/plan/concurrent/bactrian/gc_work.rs"; TR = root/"src/util/heap/gc_trigger.rs"
# --- A. marked bytes counter
patch(MOD, """    /// SATB old values handed to a ConcurrentTraceObjects packet (ProcessModBufSATB ran).
    pub static SATB_RUN: AtomicUsize = AtomicUsize::new(0);
""", """    /// SATB old values handed to a ConcurrentTraceObjects packet (ProcessModBufSATB ran).
    pub static SATB_RUN: AtomicUsize = AtomicUsize::new(0);
    /// Bytes of objects newly marked by the concurrent/sliced trace (each
    /// object once: counted when it is enqueued for scanning). Per-cycle
    /// deltas are the cycle's marked live size — the honest "live" for heap
    /// sizing and pacing under a sliced cycle, where reserved pages after the
    /// pause also contain the unswept garbage and everything born black.
    pub static MARKED_BYTES: AtomicUsize = AtomicUsize::new(0);
""")
patch(CMW, """    fn scan_and_enqueue(&mut self, object: ObjectReference) {
""", """    fn scan_and_enqueue(&mut self, object: ObjectReference) {
        crate::plan::concurrent::diag::MARKED_BYTES.fetch_add(
            VM::VMObjectModel::get_current_size(object),
            std::sync::atomic::Ordering::Relaxed,
        );
""")
# --- B. trait accessor
patch(CG, """    fn sweep_drained(&self) -> bool {
        true
    }
""", """    fn sweep_drained(&self) -> bool {
        true
    }

    /// Bytes marked by the most recently COMPLETED sliced/concurrent marking
    /// cycle (its live set at the snapshot), or 0 when the last whole-heap
    /// collection was a STW Full (whose swept reserved pages are already an
    /// honest live size) or the plan does not track it. Heap sizing and the
    /// binding's cycle-start baseline use this instead of reserved pages
    /// after a FinalMark, where reserved still contains the unswept garbage
    /// and everything promoted (born black) during the cycle.
    fn last_cycle_marked_bytes(&self) -> usize {
        0
    }

    /// Heap limit (pages) latched when the in-flight or most recent sliced
    /// cycle started; the runway the cycle's quanta are paced against. The
    /// live limit may be nudged up during the cycle so allocation never
    /// fails, but the pacing budget stays frozen. 0 = none.
    fn cycle_start_heap_pages(&self) -> usize {
        0
    }
""")
# --- C. Bactrian state
patch(GL, """    escalate_mark: AtomicBool,
    escalate_sweep: AtomicBool,
""", """    escalate_mark: AtomicBool,
    escalate_sweep: AtomicBool,
    /// diag::MARKED_BYTES at InitialMark; the cycle's marked live size is the
    /// delta at FinalMark (see ConcurrentPlan::last_cycle_marked_bytes).
    marked_bytes_at_cycle_start: AtomicU64,
    last_cycle_marked_bytes: AtomicU64,
    /// Heap limit (pages) when the current/most recent sliced cycle started —
    /// the frozen pacing runway (ConcurrentPlan::cycle_start_heap_pages).
    cycle_start_heap_pages: AtomicU64,
""")
patch(GL, """            escalate_mark: AtomicBool::new(false),
            escalate_sweep: AtomicBool::new(false),
""", """            escalate_mark: AtomicBool::new(false),
            escalate_sweep: AtomicBool::new(false),
            marked_bytes_at_cycle_start: AtomicU64::new(0),
            last_cycle_marked_bytes: AtomicU64::new(0),
            cycle_start_heap_pages: AtomicU64::new(0),
""")
patch(GL, """                self.mark_net_ewma.store(0, Ordering::Relaxed);
""", """                self.marked_bytes_at_cycle_start.store(
                    crate::plan::concurrent::diag::MARKED_BYTES.load(Ordering::Relaxed) as u64,
                    Ordering::Relaxed,
                );
                self.cycle_start_heap_pages.store(
                    self.gen.common.base.gc_trigger.policy.get_current_heap_size_in_pages() as u64,
                    Ordering::Relaxed,
                );
                self.mark_net_ewma.store(0, Ordering::Relaxed);
""")
patch(GL, """                self.sweep_packets_ewma_x256.store(0, Ordering::Relaxed);
""", """                self.sweep_packets_ewma_x256.store(0, Ordering::Relaxed);
                let marked = (crate::plan::concurrent::diag::MARKED_BYTES.load(Ordering::Relaxed) as u64)
                    .saturating_sub(self.marked_bytes_at_cycle_start.load(Ordering::Relaxed));
                self.last_cycle_marked_bytes.store(marked.max(1), Ordering::Relaxed);
""")
patch(GL, """            Pause::Full | Pause::Nursery => (),
""", """            Pause::Full => {
                // A STW Full sweeps in-pause: reserved pages after it ARE the
                // live size, so the marked-bytes channel is switched off.
                self.last_cycle_marked_bytes.store(0, Ordering::Relaxed);
                self.cycle_start_heap_pages.store(0, Ordering::Relaxed);
            }
            Pause::Nursery => (),
""")
# runway against the frozen cycle-start limit
patch(GL, """    pub(super) fn runway_pages(&self) -> usize {
        self.gen
            .common
            .base
            .gc_trigger
            .policy
            .get_current_heap_size_in_pages()
            .saturating_sub(self.get_mature_reserved_pages())
    }
""", """    pub(super) fn runway_pages(&self) -> usize {
        // Pace against the limit latched at the cycle's InitialMark, not the
        // live limit: the trigger may nudge the live limit up during a cycle
        // (so allocation never fails), and pacing against that would let the
        // budget chase the heap — the H1 ratchet.
        let frozen = self.cycle_start_heap_pages.load(Ordering::Relaxed) as usize;
        let limit = if frozen > 0 {
            frozen
        } else {
            self.gen.common.base.gc_trigger.policy.get_current_heap_size_in_pages()
        };
        limit.saturating_sub(self.get_mature_reserved_pages())
    }
""")
# trait impl on Bactrian: after fn sweep_drained
patch(GL, """    fn sweep_drained(&self) -> bool {
        !self.sweep_pending.load(Ordering::SeqCst)
    }
""", """    fn sweep_drained(&self) -> bool {
        !self.sweep_pending.load(Ordering::SeqCst)
    }

    fn last_cycle_marked_bytes(&self) -> usize {
        self.last_cycle_marked_bytes.load(Ordering::Relaxed) as usize
    }

    fn cycle_start_heap_pages(&self) -> usize {
        self.cycle_start_heap_pages.load(Ordering::Relaxed) as usize
    }
""")
# --- D. heap trigger
patch(TR, """            current_heap_pages: AtomicUsize::new(min_heap_pages),
            pending_demand_pages: AtomicUsize::new(0),
        }
""", """            current_heap_pages: AtomicUsize::new(min_heap_pages),
            pending_demand_pages: AtomicUsize::new(0),
            resize_after_sweep: AtomicBool::new(false),
        }
""")
patch(TR, """    current_heap_pages: AtomicUsize,
    /// Peak reserved pages observed while the heap was over its limit, since""",
"""    current_heap_pages: AtomicUsize,
    /// A sliced cycle's FinalMark ran with its sweep deferred: resize from the
    /// cycle's marked bytes at the first GC end whose sweep has drained.
    resize_after_sweep: AtomicBool,
    /// Peak reserved pages observed while the heap was over its limit, since""")
patch(TR, """        let clamped = target.clamp(self.min_heap_pages, self.max_heap_pages);
        if full_gc {
            self.current_heap_pages.store(clamped, Ordering::Relaxed);
        } else {
            // Grow-only on nursery GCs (the inflated reserve can overshoot, but
            // an overshot limit self-corrects at the next full GC; a frozen one
            // livelocks).
            self.current_heap_pages.fetch_max(clamped, Ordering::Relaxed);
        }
    }
""", """        let clamped = target.clamp(self.min_heap_pages, self.max_heap_pages);
        if let Some(c) = mmtk.get_plan().concurrent() {
            // Plans with sliced/concurrent major cycles. "reserved pages after
            // the pause" is NOT a live size while a cycle is in flight or its
            // sweep is deferred: it holds the unswept garbage and everything
            // promoted (born black) during the cycle, and it only grows between
            // slices. Sizing from it after every minor let the limit chase the
            // heap 1:1 (heap = 2.2 x reserved at every pause), so no cycle ever
            // felt pressure and the excursion compounded (eio_conc: 1 GB live,
            // 13-24 GB RSS). Rules here:
            //  - STW Full (marked == 0): swept live -> size from reserved, as
            //    before.
            //  - FinalMark of a sliced cycle: defer until its sweep drains, then
            //    size from the cycle's MARKED bytes, but never below what is
            //    still reserved plus the nursery headroom (the black-born pile
            //    is admitted once; the next cycle tests it and the limit comes
            //    back down).
            //  - Any other GC: the limit is only nudged up to keep allocation
            //    from failing (reserved + headroom), never multiplied. Pacing
            //    uses the limit frozen at the cycle's start (see
            //    ConcurrentPlan::cycle_start_heap_pages), so the nudge does not
            //    become runway.
            let marked = c.last_cycle_marked_bytes();
            let sweep_pending = !c.sweep_drained();
            let is_final_mark = full_gc && marked > 0;
            let floor = (live + nursery_headroom_pages).clamp(self.min_heap_pages, self.max_heap_pages);
            if full_gc && !is_final_mark {
                self.current_heap_pages.store(clamped, Ordering::Relaxed);
                self.resize_after_sweep.store(false, Ordering::Relaxed);
            } else if is_final_mark && sweep_pending {
                self.resize_after_sweep.store(true, Ordering::Relaxed);
                self.current_heap_pages.fetch_max(floor, Ordering::Relaxed);
            } else if (is_final_mark || self.resize_after_sweep.load(Ordering::Relaxed)) && !sweep_pending {
                let marked_pages = conversions::bytes_to_pages_up(marked);
                let from_marked = ((marked_pages as f64) * (1.0 + self.overhead)) as usize + nursery_headroom_pages;
                let t = std::cmp::max(from_marked, floor).clamp(self.min_heap_pages, self.max_heap_pages);
                self.current_heap_pages.store(t, Ordering::Relaxed);
                self.resize_after_sweep.store(false, Ordering::Relaxed);
            } else {
                self.current_heap_pages.fetch_max(floor, Ordering::Relaxed);
            }
            if demand > 0 {
                self.current_heap_pages.fetch_max(
                    demand_target.clamp(self.min_heap_pages, self.max_heap_pages),
                    Ordering::Relaxed,
                );
            }
        } else if full_gc {
            self.current_heap_pages.store(clamped, Ordering::Relaxed);
        } else {
            self.current_heap_pages.fetch_max(clamped, Ordering::Relaxed);
        }
    }
""")
# --- E. mark quantum: proportional floor (finish within the frozen runway)
patch(GW, """        let quota = self.budget.map(|_| {
            inflow_mark().saturating_sub(self.plan.enqueued_at_last_quantum.load(Relaxed) as usize)
        });
""", """        let quota = self.budget.map(|_| {
            let inflow = inflow_mark().saturating_sub(self.plan.enqueued_at_last_quantum.load(Relaxed) as usize);
            // Runway floor: besides its own inflow, each slice retires enough
            // of the backlog for the cycle to finish before promotion consumes
            // the runway latched at InitialMark — stock's "slice work
            // proportional to what must be done before the heap is full".
            // With no runway left, drain everything now.
            let backlog = self.plan.mark_backlog_objects();
            let (promo, runway) = self.plan.promotion_and_runway();
            let share = if runway == 0 {
                backlog
            } else if promo == 0 {
                0
            } else {
                let avail = (runway / promo).max(1) as usize;
                backlog.div_ceil(avail)
            };
            inflow + share
        });
""")
patch(GL, """    pub(super) fn note_mark_slice(&self, net: u64) -> (u64, u64) {""",
"""    /// Current promotion EWMA and frozen runway without sampling (for quota
    /// sizing at the start of a quantum; sample_promotion() folds this
    /// pause's promotion in afterwards).
    pub(super) fn promotion_and_runway(&self) -> (u64, u64) {
        (self.promotion_ewma_pages.load(Ordering::Relaxed), self.runway_pages() as u64)
    }

    pub(super) fn note_mark_slice(&self, net: u64) -> (u64, u64) {""")
# --- F. sweep quantum: proportional floor
patch(GW, """        let promo_runway = self.budget.map(|_| self.plan.sample_promotion());
        let started = std::time::Instant::now();
        let mut packets = 0usize;
        loop {
            let Some(mut w) = self.plan.pop_sweep_packet() else {""",
"""        let promo_runway = self.budget.map(|_| self.plan.sample_promotion());
        // Runway floor for the sweep: a pending cycle request waits on this
        // drain, so each slice sweeps at least its share of the remaining
        // chunks for the drain to finish before promotion consumes the frozen
        // runway; with no runway left, drain everything now. (A 2 ms slice
        // was tuned at 192 MB; at 8-15 GB it took 146-432 minors.)
        let sweep_quota = promo_runway.map(|(promo, runway)| {
            let remaining = self.plan.sweep_packets_remaining();
            if runway == 0 {
                remaining
            } else if promo == 0 {
                0
            } else {
                remaining.div_ceil((runway / promo).max(1) as usize)
            }
        });
        let started = std::time::Instant::now();
        let mut packets = 0usize;
        loop {
            let Some(mut w) = self.plan.pop_sweep_packet() else {""")
patch(GW, """            w.do_work(worker, mmtk);
            packets += 1;
            if let Some(d) = deadline {
                if std::time::Instant::now() >= d {
                    // Budget expired. If the queue emptied on this very""",
"""            w.do_work(worker, mmtk);
            packets += 1;
            if let Some(d) = deadline {
                if std::time::Instant::now() >= d && packets >= sweep_quota.unwrap_or(0) {
                    // Budget expired. If the queue emptied on this very""")
print("core OK")
# --- G. binding baseline from marked bytes
if bind:
    B = bind/"src/collection.rs"
    patch(B, """            let sweep_done = plan.concurrent().map(|c| c.sweep_drained()).unwrap_or(true);
            if was_full && sweep_done {
                LAST_FULL_GC_MATURE_PAGES.store(mature, Ordering::Relaxed);
                AWAITING_SWEEP_BASELINE.store(false, Ordering::Relaxed);
                note_swept_baseline(mature);""",
"""            let sweep_done = plan.concurrent().map(|c| c.sweep_drained()).unwrap_or(true);
            // Baseline for the cycle-start laws: after a sliced cycle the swept
            // mature size still holds everything promoted during the cycle and
            // its sweep window (born black, never tested); the margin (x2.5) and
            // cadence (2x baseline) laws then wait for multiples of that
            // (eio_conc: baseline 0.4 -> 1.7 -> 2.8 -> 6.1 GB for a ~1 GB live
            // set). Use the cycle's marked live size instead; a STW Full reports
            // 0 and keeps the swept size, which is honest there.
            let baseline_of = |mature: usize| -> usize {
                match plan.concurrent().map(|c| c.last_cycle_marked_bytes()) {
                    Some(m) if m > 0 => m.div_ceil(mmtk::util::constants::BYTES_IN_PAGE),
                    _ => mature,
                }
            };
            if was_full && sweep_done {
                LAST_FULL_GC_MATURE_PAGES.store(baseline_of(mature), Ordering::Relaxed);
                AWAITING_SWEEP_BASELINE.store(false, Ordering::Relaxed);
                note_swept_baseline(mature);""")
    patch(B, """                // First post-FinalMark pause with the sweep complete: the
                // mature count is now authoritative.
                LAST_FULL_GC_MATURE_PAGES.store(mature, Ordering::Relaxed);""",
"""                // First post-FinalMark pause with the sweep complete: the
                // mature count is now authoritative.
                LAST_FULL_GC_MATURE_PAGES.store(baseline_of(mature), Ordering::Relaxed);""")
    print("binding OK")
