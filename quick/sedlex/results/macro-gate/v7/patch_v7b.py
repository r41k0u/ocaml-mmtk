import sys, pathlib, re
root = pathlib.Path(sys.argv[1]); GL = root/"src/plan/concurrent/bactrian/global.rs"; s = GL.read_text()
def rep(old, new, flags=0):
    global s
    if new in s: print("  already"); return
    n = len(re.findall(old, s, flags)) if flags else s.count(old)
    assert n == 1, (n, old[:60]); s = re.sub(old, new, s, flags=flags) if flags else s.replace(old, new); print("  patched")
rep("""    full_pause_ewma_nanos: AtomicU64,
""", """    full_pause_ewma_nanos: AtomicU64,
    /// Mature reserved pages when the Full EWMA and the last sliced cycle's
    /// live count were sampled; the gate scales those measurements by the
    /// heap's growth since (a 99 ms Full at 300 MB predicts ~825 ms at
    /// 2.5 GB), instead of trusting a stale small number (eio: "predicted
    /// 189 ms", Full took 1.9 s; sedlex: 40 ms vs 772 ms).
    reserved_at_last_full: AtomicU64,
    reserved_at_last_cycle: AtomicU64,
""")
rep("""            full_pause_ewma_nanos: AtomicU64::new(0),
""", """            full_pause_ewma_nanos: AtomicU64::new(0),
            reserved_at_last_full: AtomicU64::new(0),
            reserved_at_last_cycle: AtomicU64::new(0),
""")
# sample reserved at the end of a Full (where the EWMA slot is updated) and at FinalMark (with traced objs)
rep("""                let prev = slot.load(Ordering::Relaxed);
                let next = if prev == 0 { dur } else { prev - prev / 4 + dur / 4 };
                slot.store(next, Ordering::Relaxed);
""", """                let prev = slot.load(Ordering::Relaxed);
                let next = if prev == 0 { dur } else { prev - prev / 4 + dur / 4 };
                slot.store(next, Ordering::Relaxed);
                if matches!(pause, Pause::Full) {
                    self.reserved_at_last_full
                        .store(self.get_mature_reserved_pages() as u64, Ordering::Relaxed);
                }
""")
rep("""                self.last_cycle_traced_objs.store(traced, Ordering::Relaxed);
""", """                self.last_cycle_traced_objs.store(traced, Ordering::Relaxed);
                self.reserved_at_last_cycle
                    .store(self.get_mature_reserved_pages() as u64, Ordering::Relaxed);
""")
# gate: growth-scaled predictions (handles both indentations)
old = r"""(?P<i>[ ]+)let full_ms =\s*self\.full_pause_ewma_nanos\.load\(Ordering::Relaxed\) as f64 / 1e6;
[ ]+let objs = self\.last_cycle_traced_objs\.load\(Ordering::Relaxed\);
[ ]+let rate = self\.mark_rate_objs_per_ms_x256\.load\(Ordering::Relaxed\);
[ ]+let pred_ms = if objs > 0 && rate > 0 \{
[ ]+objs as f64 \* 256\.0 / rate as f64
[ ]+\} else \{
[ ]+\(self\.get_mature_reserved_pages\(\) \* crate::util::constants::BYTES_IN_PAGE\)\s*as f64\s*/ 1048576\.0
[ ]+\};
"""
m = re.search(old, s); assert m, "gate anchor"
i = m.group('i')
new = "\n".join(i + l if l else l for l in """let now_pages = self.get_mature_reserved_pages().max(1) as f64;
let growth = |at: u64| if at == 0 { 1.0 } else { (now_pages / at as f64).max(1.0) };
let full_ms = self.full_pause_ewma_nanos.load(Ordering::Relaxed) as f64 / 1e6
    * growth(self.reserved_at_last_full.load(Ordering::Relaxed));
let objs = self.last_cycle_traced_objs.load(Ordering::Relaxed);
let rate = self.mark_rate_objs_per_ms_x256.load(Ordering::Relaxed);
let pred_ms = if objs > 0 && rate > 0 {
    objs as f64 * 256.0 / rate as f64
        * growth(self.reserved_at_last_cycle.load(Ordering::Relaxed))
} else {
    now_pages * crate::util::constants::BYTES_IN_PAGE as f64 / 1048576.0
};""".split("\n")) + "\n"
s = s[:m.start()] + new + s[m.end():]; print("  patched gate (growth-scaled)")
GL.write_text(s); print("v7b OK", root)
