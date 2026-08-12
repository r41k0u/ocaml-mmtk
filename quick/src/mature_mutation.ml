(* mature_mutation — write-barrier / remembered-set stress.
 *
 * The suite gap this fills (BENCHMARK-SUITE.md item 1): no other bench
 * mutates a large OLD structure, so the generational write barrier and the
 * remset-scan half of minor GCs were essentially unmeasured panel-wide.
 *
 * Shape: build a large array of refs (the array is promoted to the mature
 * heap and stays there), then overwrite random slots with FRESHLY ALLOCATED
 * young objects for many rounds. Every store is a mature-object <- young
 * pointer write: the barrier must log it, and every minor GC must scan the
 * logged set. Deterministic xorshift PRNG; output is a pure checksum.
 *
 * Size arg = rounds in millions (default 60; ~2-3s vanilla).             *)

let n_slots = 1 lsl 18                  (* 256K slots; array ~2MB, mature *)

type cell = { mutable v : int; pad : int }

let () =
  let rounds_m = try int_of_string Sys.argv.(1) with _ -> 8 in
  let rounds = rounds_m * 1_000_000 in
  let table = Array.init n_slots (fun i -> { v = i; pad = 0 }) in
  (* xorshift64* — deterministic, no stdlib Random dependency *)
  let state = ref 88172645463325252L in
  let rand () =
    let x = !state in
    let x = Int64.logxor x (Int64.shift_left x 13) in
    let x = Int64.logxor x (Int64.shift_right_logical x 7) in
    let x = Int64.logxor x (Int64.shift_left x 17) in
    state := x;
    Int64.to_int (Int64.logand x 0x7FFFFFFFFFFFFFFFL)
  in
  let acc = ref 0 in
  for i = 1 to rounds do
    let slot = rand () land (n_slots - 1) in
    (* fresh young object stored into the mature array: barrier fires *)
    table.(slot) <- { v = i; pad = slot };
    if i land 1023 = 0 then begin
      let s2 = rand () land (n_slots - 1) in
      acc := !acc lxor table.(s2).v
    end
  done;
  (* checksum over final table state *)
  let sum = ref 0 in
  for i = 0 to n_slots - 1 do
    sum := (!sum * 31 + table.(i).v) land 0x3FFFFFFFFFFFFFF
  done;
  Printf.printf "mature_mutation %d checksum %d acc %d\n" rounds_m !sum !acc
