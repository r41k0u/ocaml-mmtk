import sys, pathlib
root = pathlib.Path(sys.argv[1]); GL = root/"src/plan/concurrent/bactrian/global.rs"; s = GL.read_text()
old = """                    let feasible = minor_ms + quantum_ms <= slice_max_pause_ms();
"""
new = """                    // With runway-paced, target-capped slices the sliced pause is
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
"""
if new in s: print("already"); sys.exit(0)
assert s.count(old) == 1, s.count(old); GL.write_text(s.replace(old, new)); print("patched global.rs (v6g: slice whenever worth)")
