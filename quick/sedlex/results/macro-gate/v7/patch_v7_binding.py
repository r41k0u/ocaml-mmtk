import sys, pathlib
core = pathlib.Path(sys.argv[1]); bind = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
def patch(path, old, new, n=1):
    s = path.read_text()
    if new and new in s and s.count(old) == 0: print("  already", path.name); return
    assert s.count(old) == n, (path.name, s.count(old), old[:60]); path.write_text(s.replace(old, new)); print("  patched", path.name)
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
