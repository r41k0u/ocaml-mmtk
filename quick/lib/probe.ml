(* probe — in-mutator instrument for GC space-time shape (D2 pacing, D3 MMU).
 *
 * Symmetric by construction: pure OCaml, identical source on vanilla and on the
 * MMTk fork, no runtime patch and no privileges. A benchmark calls [tick] from
 * its hot loop; [dump] runs at exit.
 *
 * WHY IN-MUTATOR AND NOT A SEPARATE PROBE DOMAIN
 * ----------------------------------------------
 * [Gc.minor_words] reads Caml_state->stat_minor_words, i.e. the *calling
 * domain's* odometer (runtime/gc_ctrl.c, caml_gc_minor_words_unboxed).
 * [Gc.quick_stat] does aggregate across domains, but for every domain other
 * than the caller it reads sampled_gc_stats[], which is refreshed only inside
 * a GC stop-the-world section (runtime/gc_stats.c:131
 * caml_collect_gc_stats_sample_stw, called from minor_gc.c:708 and
 * major_gc.c:1899). So a probe running in its own domain would observe the
 * benchmark's allocation advancing *only at collections* — a step function that
 * encodes GC events into the very axis D2 plots them against. Reading the
 * odometer from the mutator's own domain is the only way to get a live one.
 *
 * The same choice fixes D3's cross-runtime semantics: a gap between consecutive
 * ticks is time this mutator did not make progress, whether it was stopped by
 * MMTk's stop_all_mutators or was itself running a vanilla incremental mark
 * slice. Both are "the mutator is not progressing", which is what MMU means.
 *
 * ALLOCATION DISCIPLINE (load-bearing — the probe must not skew its own input)
 * ---------------------------------------------------------------------------
 * D2's denominator IS the allocation counter, so allocation by the probe is
 * measurement error, not just overhead.
 *   - [Gc.minor_words] is [@unboxed] (stdlib/gc.mli:270): no allocation.
 *   - [Gc.quick_stat] returns a record and DOES allocate (~25 words), so it is
 *     sampled on an allocation-distance trigger, not every tick. At the 50 MB
 *     default that is ~200 calls per 10 GB allocated — around 5k words, i.e.
 *     5e-7 of the workload.
 *   - Buffers are preallocated flat arrays; the steady-state tick path stores
 *     into them and never grows them.
 *   - Mutable floats live in a flat [float array], NEVER in a record field.
 *     Measured: a [mutable float] field of a *mixed* record costs 2 words per
 *     store, because OCaml only unboxes float fields in an all-float record —
 *     so a mixed record holds a pointer to a boxed float and every store
 *     allocates one. A [float array] slot costs 0. [Unix.gettimeofday] itself
 *     allocates nothing when its result stays in float registers. With the
 *     floats moved out of the record the whole tick path measures 0.000
 *     words/tick, so the probe does not perturb its own denominator at all.
 *
 * NATIVE ONLY — the tick path is allocation-free only under ocamlopt. All of
 * the above depends on float unboxing, which the bytecode interpreter does not
 * do: every float operation there boxes. Measured, 2M ticks:
 *
 *     backend    disabled   enabled
 *     bytecode    0.000     10.000  words/tick
 *     native      0.000      0.000
 *
 * 10 words/tick would swamp D2's denominator, so the probe refuses to arm
 * under bytecode rather than quietly producing a corrupted pacing curve. This
 * costs nothing in practice: quickbench times the native builds.
 *
 * Tunables (env): PROBE_OUT (path; unset = probe disabled), PROBE_GAP_US
 * (record gaps at least this long, default 50), PROBE_SAMPLE_MB (odometer
 * sample distance, default 50), PROBE_CAP (per-domain record capacity).
 *)

let getenv_int name default =
  match int_of_string_opt (try Sys.getenv name with Not_found -> "") with
  | Some v when v > 0 -> v
  | _ -> default

let out_path = try Some (Sys.getenv "PROBE_OUT") with Not_found -> None

(* Refuse to arm under bytecode: the tick path costs 10 words/tick there (no
   float unboxing) and would corrupt the very odometer D2 divides by. Set
   PROBE_ALLOW_BYTECODE=1 to override for a deliberate D3-only run, where the
   allocation skew does not matter. *)
let bytecode = (Sys.backend_type = Sys.Bytecode)
let allow_bytecode =
  (try Sys.getenv "PROBE_ALLOW_BYTECODE" with Not_found -> "") <> ""

let enabled =
  match out_path with
  | None -> false
  | Some _ when bytecode && not allow_bytecode ->
    prerr_endline
      "probe: DISABLED under bytecode (tick path costs 10 words/tick without \
       float unboxing, which would corrupt the D2 odometer). Use a native \
       build, or set PROBE_ALLOW_BYTECODE=1 for a D3-only run.";
    false
  | Some _ -> true

(* Gap threshold in seconds. Below this a tick is "the mutator kept running". *)
let gap_thresh = float_of_int (getenv_int "PROBE_GAP_US" 50) /. 1e6

(* Odometer sample distance, in words (OCaml words are 8 bytes on 64-bit). *)
let sample_words = float_of_int (getenv_int "PROBE_SAMPLE_MB" 50) *. 1024. *. 1024. /. 8.

(* Record capacity. Small on purpose: these buffers are LIVE for the whole run,
   so their size lands in the live set — and both collectors size the heap from
   the live set, so an oversized probe buys the program a bigger heap and fewer
   collections. Measured with the original 1<<20 default (16 MiB of gap arrays),
   vanilla binarytrees went from a perfectly reproducible 61 major collections
   to 42 with the probe armed: a 31% shift in the very quantity D2 plots, from
   the instrument rather than the workload. At 1<<14 the buffers are ~370 KiB,
   under 1% of that benchmark's live set, and the count is unperturbed.
   Raise PROBE_CAP for a long run; [dropped] in the dump reports any overflow,
   so a too-small buffer is visible rather than silent. *)
let cap = getenv_int "PROBE_CAP" (1 lsl 14)

(* Per-domain state. Flat arrays only; nothing here is grown after creation.
   The two mutable floats live in [fs] rather than in record fields — see the
   allocation-discipline note above; as record fields they would cost 2 words
   per tick. Mutable *int* fields are fine: ints are immediate, never boxed. *)
let i_last = 0        (* wall time of the previous tick *)
let i_next = 1        (* minor_words value that triggers the next sample *)

type t = {
  fs : float array;              (* [| last; next_sample |] — flat, unboxed *)
  mutable ticks : int;
  (* D3: gaps *)
  mutable ngap : int;
  mutable dropped : int;         (* gaps lost to a full buffer *)
  gap_at : float array;          (* wall time the gap started *)
  gap_dur : float array;         (* gap length, seconds *)
  (* D2: odometer samples *)
  mutable nsamp : int;
  s_at : float array;            (* wall time *)
  s_words : float array;         (* this domain's cumulative minor words *)
  s_majgc : int array;           (* global major_collections *)
  s_heap : int array;            (* global heap_words *)
}

let make () = {
  fs = Array.make 2 0.0; ticks = 0;
  ngap = 0; dropped = 0;
  gap_at = Array.make cap 0.0; gap_dur = Array.make cap 0.0;
  nsamp = 0;
  s_at = Array.make 4096 0.0; s_words = Array.make 4096 0.0;
  s_majgc = Array.make 4096 0; s_heap = Array.make 4096 0;
}

(* Every domain that ticks gets its own [t]; DLS keeps the hot path free of any
   cross-domain synchronisation. Registered copies are kept for the dump. *)
let all : (int * t) list ref = ref []
let all_mu = Mutex.create ()

let key : t option Domain.DLS.key = Domain.DLS.new_key (fun () -> None)

let register () =
  let t = make () in
  Domain.DLS.set key (Some t);
  Mutex.lock all_mu;
  all := ((Domain.self () :> int), t) :: !all;
  Mutex.unlock all_mu;
  t.fs.(i_last) <- Unix.gettimeofday ();
  t.fs.(i_next) <- Gc.minor_words ();
  t

let state () =
  match Domain.DLS.get key with Some t -> t | None -> register ()

(* Hot path. Call from a benchmark's inner loop, often enough that a normal
   inter-tick interval is well under a GC pause. *)
let tick () =
  if enabled then begin
    let t = state () in
    let now = Unix.gettimeofday () in
    let dt = now -. t.fs.(i_last) in
    if dt >= gap_thresh then begin
      if t.ngap < cap then begin
        t.gap_at.(t.ngap) <- t.fs.(i_last);
        t.gap_dur.(t.ngap) <- dt;
        t.ngap <- t.ngap + 1
      end else
        t.dropped <- t.dropped + 1
    end;
    t.fs.(i_last) <- now;
    t.ticks <- t.ticks + 1;
    let mw = Gc.minor_words () in
    if mw >= t.fs.(i_next) && t.nsamp < Array.length t.s_at then begin
      (* The one allocating call, deliberately rare. *)
      let q = Gc.quick_stat () in
      t.s_at.(t.nsamp) <- now;
      t.s_words.(t.nsamp) <- mw;
      t.s_majgc.(t.nsamp) <- q.Gc.major_collections;
      t.s_heap.(t.nsamp) <- q.Gc.heap_words;
      t.nsamp <- t.nsamp + 1;
      t.fs.(i_next) <- mw +. sample_words
    end
  end

(* Wrap a domain body so spawned workers are registered and flushed even if the
   benchmark never calls [tick] on the main domain. *)
let with_domain f x = ignore (state ()); f x

let dump () =
  match out_path with
  | None -> ()
  | Some path ->
    let oc = open_out path in
    let fin = Gc.quick_stat () in
    Printf.fprintf oc
      "{\"kind\":\"summary\",\"backend\":\"%s\",\"domains\":%d,\
       \"final_minor_words\":%.0f,\"final_major_collections\":%d,\
       \"gap_threshold_us\":%.0f,\"sample_mb\":%.0f}\n"
      (if bytecode then "bytecode" else "native")
      (List.length !all) (Gc.minor_words ()) fin.Gc.major_collections
      (gap_thresh *. 1e6) (sample_words *. 8. /. 1024. /. 1024.);
    List.iter (fun (did, t) ->
      (* probe_words: the probe's own allocation. The tick path is measured at
         0 words; only the rare quick_stat sample allocates (~25 words). Kept
         explicit so analysis can subtract it and so a regression to a boxing
         tick path would show up as a nonzero per-tick term. *)
      Printf.fprintf oc
        "{\"kind\":\"domain\",\"domain\":%d,\"ticks\":%d,\"gaps\":%d,\
         \"samples\":%d,\"dropped\":%d,\"probe_words\":%d}\n"
        did t.ticks t.ngap t.nsamp t.dropped (25 * t.nsamp);
      for i = 0 to t.ngap - 1 do
        Printf.fprintf oc "{\"kind\":\"gap\",\"domain\":%d,\"at\":%.9f,\"dur\":%.9f}\n"
          did t.gap_at.(i) t.gap_dur.(i)
      done;
      for i = 0 to t.nsamp - 1 do
        Printf.fprintf oc
          "{\"kind\":\"sample\",\"domain\":%d,\"at\":%.9f,\"minor_words\":%.0f,\
           \"major_collections\":%d,\"heap_words\":%d}\n"
          did t.s_at.(i) t.s_words.(i) t.s_majgc.(i) t.s_heap.(i)
      done) !all;
    close_out oc

let () = if enabled then at_exit dump
