(* weak_memo — weak-reference / clear-timing workload.
 *
 * The suite gap this fills (BENCHMARK-SUITE.md item 2): nothing in the panel
 * allocates a single Weak.t, though Bactrian's clear timing (at cycle
 * completion) differs structurally from vanilla's (incremental).
 *
 * Shape: a memo table of Weak pointers over generations of boxed values.
 * Strong roots for the current generation are held in an array; each wave
 * drops the previous generation's strong refs (their weak entries become
 * clearable at the collector's leisure) and installs a new generation.
 *
 * OUTPUT DISCIPLINE (gating): stdout carries ONLY collector-independent
 * invariants — (a) strongly-held entries must NEVER read as cleared (an
 * assertion, and part of the checksum), (b) a checksum over the strong
 * values. The GC-DEPENDENT quantities (how many dead entries were observed
 * cleared, i.e. clear latency) go to STDERR as measurement, not gate.
 *
 * Size arg = waves (default 400; ~1.5-2s vanilla).                       *)

let gen_size = 16384                     (* live strong set per wave *)

let () =
  let waves = try int_of_string Sys.argv.(1) with _ -> 800 in
  let weak : int ref Weak.t = Weak.create (gen_size * 2) in
  let strong = Array.init gen_size (fun i -> ref i) in
  let cleared_seen = ref 0 and dead_total = ref 0 in
  let checksum = ref 0 in
  for w = 1 to waves do
    (* install current generation in the weak table (even slots) *)
    for i = 0 to gen_size - 1 do
      Weak.set weak (2 * i) (Some strong.(i))
    done;
    (* probe: every strongly-held entry MUST be present *)
    for i = 0 to gen_size - 1 do
      match Weak.get weak (2 * i) with
      | Some r -> checksum := (!checksum * 7 + !r) land 0x3FFFFFFFFFFFFFF
      | None -> prerr_endline "INVARIANT VIOLATION: strong entry cleared";
                exit 2
    done;
    (* move current gen into the odd slots WITHOUT strong refs (they die),
       then replace the strong generation *)
    for i = 0 to gen_size - 1 do
      Weak.set weak (2 * i + 1) (Some strong.(i))
    done;
    for i = 0 to gen_size - 1 do
      strong.(i) <- ref (w * gen_size + i)
    done;
    dead_total := !dead_total + gen_size;
    (* count observed clears of dead entries: GC-timing dependent -> stderr *)
    for i = 0 to gen_size - 1 do
      if Weak.get weak (2 * i + 1) = None then incr cleared_seen
    done
  done;
  Printf.eprintf "weak_memo: dead=%d observed-cleared=%d (timing metric)\n"
    !dead_total !cleared_seen;
  Printf.printf "weak_memo %d checksum %d\n" waves !checksum
