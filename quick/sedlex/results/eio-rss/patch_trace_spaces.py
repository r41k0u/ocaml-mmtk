import sys, pathlib
root = pathlib.Path(sys.argv[1]); p = root/"src/plan/concurrent/bactrian/global.rs"; s = p.read_text()
old = '''                "[bactrian] {} {:?} (marking={}, mature_pages={}, seeded={}, enq={}, traced={}, skipped_young={}, satb={}, satb_young_drop={})",
                what,
                pause,
                self.concurrent_marking_in_progress(),
                self.immix_space.reserved_pages(),'''
new = '''                "[bactrian] {} {:?} (marking={}, mature_pages={}, reserved={}, immix={}, los={}, nonmoving={}, nursery={}, heap={}, sweep_pending={}, seeded={}, enq={}, traced={}, skipped_young={}, satb={}, satb_young_drop={})",
                what,
                pause,
                self.concurrent_marking_in_progress(),
                self.immix_space.reserved_pages(),
                self.get_reserved_pages(),
                self.immix_space.reserved_pages(),
                self.gen.common.get_los().reserved_pages(),
                self.gen.common.get_nonmoving().reserved_pages(),
                self.gen.nursery.reserved_pages(),
                self.gen.common.base.gc_trigger.policy.get_current_heap_size_in_pages(),
                self.sweep_pending.load(Ordering::SeqCst),'''
if new in s: print("already"); sys.exit(0)
assert s.count(old) == 1, s.count(old); p.write_text(s.replace(old, new)); print("patched trace_pause")
