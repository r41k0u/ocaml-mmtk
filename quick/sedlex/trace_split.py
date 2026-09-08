import json, sys, collections
open_ts = collections.defaultdict(list); dur = collections.Counter(); cnt = collections.Counter()
for line in open(sys.argv[1], errors="replace"):
    s = line.strip().rstrip(",")
    if not s.startswith("{"): continue
    try: e = json.loads(s)
    except Exception: continue
    ph, name, ts = e.get("ph"), e.get("name"), e.get("ts")
    if ph == "B": open_ts[name].append(ts)
    elif ph == "E" and open_ts[name]:
        dur[name] += ts - open_ts[name].pop(); cnt[name] += 1
print(f"{'event':36s} {'n':>6s} {'total(s)':>9s} {'mean(us)':>9s}")
for name, d in sorted(dur.items(), key=lambda kv: -kv[1]):
    print(f"{name:36s} {cnt[name]:6d} {d/1e6:9.3f} {d/cnt[name]:9.1f}")
m, M = dur.get("minor",0)/1e6, dur.get("major",0)/1e6
print(f"\nminor total {m:.3f}s + major total {M:.3f}s = {m+M:.3f}s (olly gc-stats said 2.78s)")
