(* fragmed — mature-space fragmentation driver.
 *
 * The suite gap this fills (BENCHMARK-SUITE.md item 4, made mandatory by the
 * auto-compaction calibration: no existing bench leaves the mature space
 * with many partially-occupied blocks at steady state).
 *
 * Shape: allocate waves of medium blocks (~3KB — the pretenured, mature-born
 * band under Bactrian; heap-allocated under vanilla), KEEP every 16th one
 * long-term (scattered survivors pin their 32KB Immix blocks / vanilla pool
 * chunks at low occupancy), drop the rest, and keep churning. Steady state:
 * live bytes are a small fraction of touched mature bytes unless the
 * collector compacts. Deterministic; output is a checksum over survivors.
 *
 * Size arg = waves (default 300; ~1.5-2.5s vanilla).                     *)

let wave_objs = 512                      (* per wave: 512 x ~3KB = ~1.5MB *)
let obj_words = 384                      (* ~3KB + header: pretenure band *)
let keep_every = 16

let () =
  let waves = try int_of_string Sys.argv.(1) with _ -> 150 in
  let keepers : int array array =
    Array.make (waves * wave_objs / keep_every + 1) [||] in
  let n_keep = ref 0 in
  let checksum = ref 0 in
  for w = 1 to waves do
    for k = 0 to wave_objs - 1 do
      let a = Array.make obj_words (w * wave_objs + k) in
      a.(0) <- w; a.(obj_words - 1) <- k;
      if k mod keep_every = 0 then begin
        keepers.(!n_keep) <- a;
        incr n_keep
      end
      (* else: a dies young-or-mature depending on the collector's law *)
    done;
    (* touch survivors so they stay genuinely live and cache-visible *)
    if w land 15 = 0 then begin
      for i = 0 to !n_keep - 1 do
        checksum := (!checksum * 17 + keepers.(i).(0) + keepers.(i).(obj_words - 1))
                    land 0x3FFFFFFFFFFFFFF
      done
    end
  done;
  Printf.printf "fragmed %d keepers %d checksum %d\n" waves !n_keep !checksum
