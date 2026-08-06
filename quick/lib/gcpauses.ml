(* gcpauses — D3 on the VANILLA side, with no probe and no overhead.
 *
 * The in-mutator probe cannot serve D3 on a coarse-grained workload: a gap only
 * means "the mutator was stopped" if the work between ticks is far below the
 * pause scale, and making it so costs 44% wall (see lib/probe.ml). So D3 uses
 * the authoritative, zero-overhead source on each side:
 *
 *     fork     MMTK_PAUSE_LOG            (collection.rs, backlog #R1)
 *     vanilla  runtime_events            (this program)
 *
 * The instruments differ; the DEFINITION does not, which is what matters. Both
 * yield intervals during which the mutator makes no program progress:
 *
 *   - MMTk: stop_all_mutators -> resume_mutators, the mutator is parked.
 *   - vanilla: EV_MINOR, the mutator is stopped for a minor collection; and
 *     EV_MAJOR_SLICE, the mutator is running GC work instead of program work.
 *     Vanilla's major GC is incremental ON the mutator domains, so a slice is
 *     not a "pause" in the stop-the-world sense — but it is time the program is
 *     not advancing, and that is precisely what MMU is defined over.
 *
 * Runs as a SEPARATE PROCESS reading the target's ring buffer by (dir, pid), so
 * the target pays only the ring writes runtime_events is designed to always
 * afford. Polling continuously also drains the ring, so a long run cannot lose
 * early events to wraparound the way an at-exit read could.
 *
 * Emits the same NDJSON as MMTK_PAUSE_LOG — {"kind":"pause","at","dur","full"} —
 * so shapeplot consumes both sides through one path. "full" marks major-GC
 * phases so the nursery/full split stays visible, as on the MMTk side.
 *
 * Usage:  gcpauses <events-dir> <pid> <out.ndjson>
 *)

let phase_name p =
  (* Only the phases that represent "the mutator is not advancing". Sub-phases
     (EV_MINOR_LOCAL_ROOTS etc.) nest inside these and would double-count. *)
  match p with
  | Runtime_events.EV_MINOR -> Some ("minor", false)
  | Runtime_events.EV_MAJOR_SLICE -> Some ("major_slice", true)
  | Runtime_events.EV_MAJOR_GC_STW -> Some ("major_stw", true)
  | Runtime_events.EV_COMPACT -> Some ("compact", true)
  | _ -> None

let () =
  let dir = Sys.argv.(1) and pid = int_of_string Sys.argv.(2) in
  let out_path = Sys.argv.(3) in

  (* The ring appears shortly after the target starts; wait for it rather than
     racing the exec. *)
  let cursor =
    let rec attempt n =
      match Runtime_events.create_cursor (Some (dir, pid)) with
      | c -> c
      | exception e ->
        if n = 0 then raise e else (Unix.sleepf 0.01; attempt (n - 1))
    in
    attempt 500
  in

  let oc = open_out out_path in
  (* Timestamps are nanoseconds from an unspecified origin, so rebase on the
     first event seen to match the MMTk log's relative timeline. *)
  let t0 = ref None in
  let rel ts =
    let v = Int64.to_float (Runtime_events.Timestamp.to_int64 ts) /. 1e9 in
    match !t0 with None -> t0 := Some v; 0.0 | Some z -> v -. z
  in
  let open_spans = Hashtbl.create 64 in
  let n = ref 0 and lost = ref 0 in

  let runtime_begin d ts p =
    match phase_name p with
    | None -> ()
    | Some _ -> Hashtbl.replace open_spans (d, p) (rel ts)
  in
  let runtime_end d ts p =
    match phase_name p with
    | None -> ()
    | Some (name, full) ->
      (match Hashtbl.find_opt open_spans (d, p) with
       | None -> ()   (* end without a begin: the cursor attached mid-span *)
       | Some start ->
         Hashtbl.remove open_spans (d, p);
         let stop = rel ts in
         if stop >= start then begin
           incr n;
           Printf.fprintf oc
             "{\"kind\":\"pause\",\"at\":%.9f,\"dur\":%.9f,\"full\":%b,\
              \"phase\":\"%s\",\"domain\":%d}\n"
             start (stop -. start) full name d
         end)
  in
  let lost_events _ k = lost := !lost + k in
  let cb = Runtime_events.Callbacks.create ~runtime_begin ~runtime_end
             ~lost_events () in

  (* Poll until the target is gone, then drain whatever it left behind. *)
  let alive () = try Unix.kill pid 0; true with Unix.Unix_error _ -> false in
  while alive () do
    ignore (Runtime_events.read_poll cursor cb None);
    Unix.sleepf 0.001
  done;
  ignore (Runtime_events.read_poll cursor cb None);
  Runtime_events.free_cursor cursor;

  Printf.fprintf oc
    "{\"kind\":\"pause_summary\",\"source\":\"runtime_events\",\"pauses\":%d,\
     \"lost_events\":%d}\n" !n !lost;
  close_out oc;
  if !lost > 0 then
    Printf.eprintf
      "gcpauses: WARNING %d events lost to ring wraparound — the record is \
       incomplete; raise the ring size or poll faster.\n" !lost
