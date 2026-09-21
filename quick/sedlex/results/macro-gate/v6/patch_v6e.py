import sys, pathlib
root = pathlib.Path(sys.argv[1]); GL = root/"src/plan/concurrent/bactrian/global.rs"; GW = root/"src/plan/concurrent/bactrian/gc_work.rs"
def patch(path, old, new):
    s = path.read_text()
    if new in s: print("  already", path.name); return
    assert s.count(old) == 1, (path.name, s.count(old), old[:60]); path.write_text(s.replace(old, new)); print("  patched", path.name)
patch(GL, """    full_pause_ewma_nanos: AtomicU64,
""", """    full_pause_ewma_nanos: AtomicU64,
    /// Nanoseconds spent in mark/sweep quanta during the current pause; the
    /// nursery-pause EWMA is taken NET of it, otherwise runway-sized slices
    /// inflate the very average the slicing gate and the latency start use
    /// to decide whether slicing fits (v6d: EWMA > 100 ms -> 44 Fulls).
    quanta_nanos_this_pause: AtomicU64,
""")
patch(GL, """            full_pause_ewma_nanos: AtomicU64::new(0),
""", """            full_pause_ewma_nanos: AtomicU64::new(0),
            quanta_nanos_this_pause: AtomicU64::new(0),
""")
patch(GL, """        self.pause_start_nanos.store(now_nanos(), Ordering::Relaxed);
        self.mature_at_prepare""", """        self.pause_start_nanos.store(now_nanos(), Ordering::Relaxed);
        self.quanta_nanos_this_pause.store(0, Ordering::Relaxed);
        self.mature_at_prepare""")
patch(GL, """            if start != 0 {
                let dur = now_nanos().saturating_sub(start);
                let slot = if matches!(pause, Pause::Nursery) {""", """            if start != 0 {
                let dur = now_nanos()
                    .saturating_sub(start)
                    .saturating_sub(self.quanta_nanos_this_pause.load(Ordering::Relaxed));
                let slot = if matches!(pause, Pause::Nursery) {""")
patch(GL, """    pub(super) fn slice_target_ms(&self) -> f64 {
        let minor_ms = self.nursery_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
        (slice_max_pause_ms() - minor_ms).max(10.0)
    }
""", """    pub(super) fn slice_target_ms(&self) -> f64 {
        let minor_ms = self.nursery_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6;
        (slice_max_pause_ms() - minor_ms).max(25.0)
    }

    pub(super) fn note_quantum_nanos(&self, nanos: u64) {
        self.quanta_nanos_this_pause.fetch_add(nanos, Ordering::Relaxed);
    }
""")
patch(GL, """                        let target = (slice_max_pause_ms() - minor_ms).max(10.0);
                        let per_slice""", """                        let target = (slice_max_pause_ms() - minor_ms).max(25.0);
                        let per_slice""")
patch(GW, """        self.plan.note_mark_rate(
            (TRACED.load(Relaxed) - traced_at_start) as u64,
            started.elapsed().as_nanos() as u64,
        );
""", """        self.plan.note_mark_rate(
            (TRACED.load(Relaxed) - traced_at_start) as u64,
            started.elapsed().as_nanos() as u64,
        );
        self.plan.note_quantum_nanos(started.elapsed().as_nanos() as u64);
""")
patch(GW, """        if let Some((promo, runway)) = promo_runway {
            // Projection guard for the sweep:""", """        self.plan.note_quantum_nanos(started.elapsed().as_nanos() as u64);
        if let Some((promo, runway)) = promo_runway {
            // Projection guard for the sweep:""")
print("v6e OK", root)
