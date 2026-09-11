import sys, pathlib
root = pathlib.Path(sys.argv[1])
def patch(rel, old, new, n=1):
    p = root / rel; s = p.read_text(); c = s.count(old)
    if new in s: print("  already", rel); return
    assert c == n, f"{rel}: found {c} != {n} of {old[:60]!r}"
    p.write_text(s.replace(old, new)); print("  patched", rel)
GW = "src/plan/concurrent/bactrian/gc_work.rs"
# v3: quota work FIRST, then the time budget (sum, not max): the time budget
# keeps its original job — working the backlog — instead of being absorbed by
# the inflow.
patch(GW, """        let deadline = self.budget.map(|b| std::time::Instant::now() + b);
        // Work floor (budgeted quanta only): drain at least as many objects as
        // were handed to marking packets since the previous quantum finished —
        // SATB old values the barrier parked between pauses and at mutator
        // flush, plus the nursery closure's seeds. The time budget alone is a
        // rate guess (debt over runway pauses at an assumed mark rate,
        // re-derived every minor against a heap that grows while the cycle is
        // open); if the inflow outruns it the parked queue only grows and the
        // cycle never reaches FinalMark. With the floor a quantum always
        // retires its own inflow, and the time budget works the original
        // debt on top. The quantum's own child packets are not inflow: the
        // snapshot is taken after the drain.
""", """        // Work floor (budgeted quanta only): first drain at least as many
        // objects as were handed to marking packets since the previous quantum
        // finished — SATB old values the barrier parked between pauses and at
        // mutator flush, plus the nursery closure's seeds — and only THEN run
        // the time budget. The time budget alone is a rate guess (debt over
        // runway pauses at an assumed mark rate, re-derived every minor against
        // a heap that grows while the cycle is open); if the inflow outruns it
        // the parked queue only grows and the cycle never reaches FinalMark
        // (eio_conc: 60-125k SATB entries per minor vs ~50k traced in a 2-5 ms
        // quantum; the queue hovered at ~1M objects for 1600 minors, RSS 3 ->
        // 24 GB). Inflow and budget ADD: a max() of the two only holds the
        // queue steady and never drains it. The quantum's own child packets are
        // not inflow: the snapshot is taken after the drain.
""")
patch(GW, """        let traced_at_start = TRACED.load(Relaxed);
        let started = std::time::Instant::now();
        let mut packets = 0usize;
""", """        let traced_at_start = TRACED.load(Relaxed);
        let started = std::time::Instant::now();
        // Armed once the quota is met; None while the floor is being worked.
        let mut deadline: Option<std::time::Instant> = None;
        let mut packets = 0usize;
""")
patch(GW, """            if let Some(d) = deadline {
                if std::time::Instant::now() >= d
                    && TRACED.load(Relaxed) - traced_at_start >= quota.unwrap_or(0)
                {
                    break;
                }
            }
""", """            if let Some(b) = self.budget {
                match deadline {
                    None => {
                        if TRACED.load(Relaxed) - traced_at_start >= quota.unwrap_or(0) {
                            deadline = Some(std::time::Instant::now() + b);
                        }
                    }
                    Some(d) => {
                        if std::time::Instant::now() >= d {
                            break;
                        }
                    }
                }
            }
""")
print("OK", root)
