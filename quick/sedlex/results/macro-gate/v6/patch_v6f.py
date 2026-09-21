import sys, pathlib
root = pathlib.Path(sys.argv[1]); GW = root/"src/plan/concurrent/bactrian/gc_work.rs"; s = GW.read_text()
old = """            let escalate = !drained && slices >= 4 && need > avail;
            if escalate {
                self.plan.request_escalate_mark();
            }
"""
new = """            // With the runway-paced, target-capped share above, the slices
            // already finish the cycle inside the runway or overshoot it by a
            // bounded amount; an unbudgeted drain here would just be the
            // multi-second pause the cap exists to avoid (v6e eio: 14
            // escalations = 11 pauses > 500 ms). Report, don't escalate.
            let escalate = !drained && slices >= 4 && need > avail;
"""
if new in s: print("already"); sys.exit(0)
assert s.count(old) == 1, s.count(old); GW.write_text(s.replace(old, new)); print("patched gc_work.rs (v6f: no mark escalation)")
