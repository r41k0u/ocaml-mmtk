import sys, pathlib, re
GL = pathlib.Path(sys.argv[1])/"src/plan/concurrent/bactrian/global.rs"; s = GL.read_text()
pat = re.compile(r"(?P<i>[ ]+)let pred_ms = if objs > 0 && rate > 0 \{\n[ ]+objs as f64 \* 256\.0 / rate as f64\n[ ]+\* growth\(self\.reserved_at_last_cycle\.load\(Ordering::Relaxed\)\)\n[ ]+\} else \{\n[ ]+now_pages \* crate::util::constants::BYTES_IN_PAGE as f64 / 1048576\.0\n[ ]+\};\n")
m = pat.search(s)
if not m: print("already" if "mature_ms.max(" in s else "ANCHOR MISSING"); sys.exit(0 if "mature_ms.max(" in s else 1)
i = m.group('i')
new = "\n".join(i + l if l else l for l in """// Mature bytes at 1 MB/ms is a floor, not just a bootstrap: the last
// sliced cycle's traced count misses everything promoted black during
// it, which on a monotonically growing live set (sedlex: back-to-back
// tick-origin cycles) is most of the heap — "predicted 44 ms" for a
// Full that took 865 ms.
let mature_ms = now_pages * crate::util::constants::BYTES_IN_PAGE as f64 / 1048576.0;
let pred_ms = if objs > 0 && rate > 0 {
    mature_ms.max(
        objs as f64 * 256.0 / rate as f64
            * growth(self.reserved_at_last_cycle.load(Ordering::Relaxed)),
    )
} else {
    mature_ms
};""".split("\n")) + "\n"
s = s[:m.start()] + new + s[m.end():]; GL.write_text(s); print("patched v7c", GL.parent.parent.parent.parent)
