import sys, pathlib
root = pathlib.Path(sys.argv[1]); GL = root/"src/plan/concurrent/bactrian/global.rs"; GW = root/"src/plan/concurrent/bactrian/gc_work.rs"
def patch(path, old, new):
    s = path.read_text()
    if new in s: print("  already", path.name); return
    assert s.count(old) == 1, (path.name, s.count(old), old[:60]); path.write_text(s.replace(old, new)); print("  patched", path.name)
# state: measured mark rate (objects per ms, EWMA) and the latency start law's inputs
patch(GL, """    full_pause_ewma_nanos: AtomicU64,
""", """    full_pause_ewma_nanos: AtomicU64,
    /// EWMA (alpha 1/4, x256 fixed point) of objects traced per millisecond
    /// inside mark quanta: the measured mark rate, for sizing slices and for
    /// the latency-aware cycle start. 0 = no sample yet.
    mark_rate_objs_per_ms_x256: AtomicU64,
    /// Objects traced by the most recently completed sliced cycle (its live
    /// object count), for predicting the next cycle's marking time.
    last_cycle_traced_objs: AtomicU64,
    traced_at_cycle_start: AtomicU64,
""")
patch(GL, """            full_pause_ewma_nanos: AtomicU64::new(0),
""", """            full_pause_ewma_nanos: AtomicU64::new(0),
            mark_rate_objs_per_ms_x256: AtomicU64::new(0),
            last_cycle_traced_objs: AtomicU64::new(0),
            traced_at_cycle_start: AtomicU64::new(0),
""")
patch(GL, """                self.marked_bytes_at_cycle_start.store(
                    crate::plan::concurrent::diag::MARKED_BYTES.load(Ordering::Relaxed) as u64,
                    Ordering::Relaxed,
                );
""", """                self.marked_bytes_at_cycle_start.store(
                    crate::plan::concurrent::diag::MARKED_BYTES.load(Ordering::Relaxed) as u64,
                    Ordering::Relaxed,
                );
                self.traced_at_cycle_start.store(
                    crate::plan::concurrent::diag::TRACED.load(Ordering::Relaxed) as u64,
                    Ordering::Relaxed,
                );
""")
patch(GL, """                self.last_cycle_marked_bytes.store(marked.max(1), Ordering::Relaxed);
""", """                self.last_cycle_marked_bytes.store(marked.max(1), Ordering::Relaxed);
                let traced = (crate::plan::concurrent::diag::TRACED.load(Ordering::Relaxed) as u64)
                    .saturating_sub(self.traced_at_cycle_start.load(Ordering::Relaxed));
                self.last_cycle_traced_objs.store(traced, Ordering::Relaxed);
""")
# latency-aware start: evaluated at the end of an idle nursery pause
patch(GL, """            Pause::Nursery => (),
        }
""", """            Pause::Nursery => {
                // Latency-aware cycle start. With honest heap sizing the
                // runway is ~1.2 x live; a large live set at Bactrian's mark
                // rate cannot be marked within it at small slices if the
                // cycle starts only at the margin law's 0.8 x limit (sedlex
                // 6M: 8 GB live, 4.8 MB promoted per minor -> the runway floor
                // degenerated into 16-38 s drain-all slices). Start as soon as
                // the predicted marking time, spread over the minors left
                // before the heap fills, exceeds the per-slice target.
                if !self.concurrent_marking_in_progress()
                    && !self.sweep_pending.load(Ordering::SeqCst)
                    && !self.major_request_pending()
                {
                    let objs = self.last_cycle_traced_objs.load(Ordering::Relaxed);
                    let rate = self.mark_rate_objs_per_ms_x256.load(Ordering::Relaxed);
                    if objs > 0 && rate > 0 {
                        let mark_ms = objs as f64 * 256.0 / rate as f64;
                        let promo = self.promotion_ewma_pages.load(Ordering::Relaxed);
                        let runway = self
                            .gen
                            .common
                            .base
                            .gc_trigger
                            .policy
                            .get_current_heap_size_in_pages()
                            .saturating_sub(self.get_mature_reserved_pages()) as u64;
                        let fill_minors = if promo == 0 { u64::MAX } else { (runway / promo).max(1) };
                        let minor_ms =
                            self.nursery_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
                        let target = (slice_max_pause_ms() - minor_ms).max(10.0);
                        let per_slice = if fill_minors == u64::MAX { 0.0 } else { mark_ms / fill_minors as f64 };
                        if per_slice > target {
                            if std::env::var_os("MMTK_PACE_DEBUG").is_some() {
                                eprintln!(
                                    "[pace] latency start: mark_ms={:.0} fill_minors={} per_slice={:.0}ms > target={:.0}ms -> request cycle",
                                    mark_ms, fill_minors, per_slice, target
                                );
                            }
                            self.gen.force_full_heap_collection();
                        }
                    }
                }
            }
        }
""")
patch(GL, """    pub(super) fn note_mark_slice(&self, net: u64) -> (u64, u64) {""",
"""    /// Fold a quantum's measured throughput (objects traced over its wall
    /// time) into the mark-rate EWMA; returns the current rate x256.
    pub(super) fn note_mark_rate(&self, traced: u64, nanos: u64) -> u64 {
        if nanos < 200_000 || traced == 0 {
            return self.mark_rate_objs_per_ms_x256.load(Ordering::Relaxed);
        }
        let sample = traced * 256 * 1_000_000 / nanos;
        let prev = self.mark_rate_objs_per_ms_x256.load(Ordering::Relaxed);
        let next = if prev == 0 { sample } else { prev - prev / 4 + sample / 4 };
        self.mark_rate_objs_per_ms_x256.store(next, Ordering::Relaxed);
        next
    }

    /// Per-slice mark target in ms: the pause budget minus the recent nursery
    /// pause, floor 10 ms.
    pub(super) fn slice_target_ms(&self) -> f64 {
        let minor_ms = self.nursery_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
        (slice_max_pause_ms() - minor_ms).max(10.0)
    }

    pub(super) fn mark_rate_x256(&self) -> u64 {
        self.mark_rate_objs_per_ms_x256.load(Ordering::Relaxed)
    }

    pub(super) fn note_mark_slice(&self, net: u64) -> (u64, u64) {""")
# mark quantum: capped share
patch(GW, """            let backlog = self.plan.mark_backlog_objects();
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
""", """            let backlog = self.plan.mark_backlog_objects();
            let (promo, runway) = self.plan.promotion_and_runway();
            // Minors the runway allows; never fewer than the slices needed to
            // keep each slice within the pause target at the measured mark
            // rate. Past the runway the heap overshoots the frozen limit by
            // promotion x the slices left — bounded — instead of one slice
            // draining everything (sedlex: 16-38 s).
            let avail_runway = if promo == 0 { u64::MAX } else { (runway / promo).max(1) };
            let rate = self.plan.mark_rate_x256();
            let min_slices = if rate == 0 {
                1
            } else {
                let backlog_ms = backlog as f64 * 256.0 / rate as f64;
                (backlog_ms / self.plan.slice_target_ms()).ceil().max(1.0) as u64
            };
            let avail = std::cmp::max(std::cmp::min(avail_runway, u64::MAX / 2), min_slices) as usize;
            let share = if promo == 0 && rate == 0 { 0 } else { backlog.div_ceil(avail) };
            inflow + share
""")
patch(GW, """        self.plan
            .enqueued_at_last_quantum
            .store(inflow_mark() as u64, Relaxed);
""", """        self.plan
            .enqueued_at_last_quantum
            .store(inflow_mark() as u64, Relaxed);
        self.plan.note_mark_rate(
            (TRACED.load(Relaxed) - traced_at_start) as u64,
            started.elapsed().as_nanos() as u64,
        );
""")
# sweep quantum: time-capped share (20 ms) unless the runway is gone
patch(GW, """        let sweep_quota = promo_runway.map(|(promo, runway)| {
            let remaining = self.plan.sweep_packets_remaining();
            if runway == 0 {
                remaining
            } else if promo == 0 {
                0
            } else {
                remaining.div_ceil((runway / promo).max(1) as usize)
            }
        });
""", """        let sweep_quota = promo_runway.map(|(promo, runway)| {
            let remaining = self.plan.sweep_packets_remaining();
            if promo == 0 {
                0
            } else {
                remaining.div_ceil((runway / promo).max(1) as usize)
            }
        });
        // Soft time cap on the share (MMTK_SWEEP_SLICE_CAP_MS, default 20):
        // past the runway the next cycle waits a little longer rather than
        // one slice sweeping gigabytes.
        let cap = std::time::Duration::from_secs_f64(
            std::env::var("MMTK_SWEEP_SLICE_CAP_MS").ok().and_then(|v| v.parse::<f64>().ok()).unwrap_or(20.0) / 1e3,
        );
""")
patch(GW, """                if std::time::Instant::now() >= d && packets >= sweep_quota.unwrap_or(0) {""",
"""                let now = std::time::Instant::now();
                if now >= d && (packets >= sweep_quota.unwrap_or(0) || now >= started + cap) {""")
print("v6d OK", root)
