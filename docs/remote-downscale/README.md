# Remote downscale workers — design overview

Status: phases 1–3 implemented (ffmpeg argv persistence, TA worker API —
see [ta-server.md](ta-server.md) — and the worker script, see
[worker.md](worker.md)). Phase 4 (polish) is still design draft.

**Never run against real hardware.** Everything here has been verified
by code-level testing on the TA side only; no job has been encoded on
the 5090. See [windows-host-setup.md](windows-host-setup.md) for the
first-run runbook and the list of things still unconfirmed.

Companion docs:

- [ta-server.md](ta-server.md) — TubeArchivist-side changes: worker API, job
  document schema, lease/reaper, dispatch semantics
- [worker.md](worker.md) — the sister application that runs on a remote host
  (initially a Windows gaming PC with an RTX 5090)
- [windows-host-setup.md](windows-host-setup.md) — bringing that host up
  for the first time: what to verify, in what order, and what the open
  questions are
- [../downscale-hdr/README.md](../downscale-hdr/README.md) — HDR
  detection and preservation, which is why the worker uses HandBrake at
  all

## Motivation

TA runs on a Raspberry Pi 5 (eventually an Unraid server). Software AV1
encoding on the Pi is slow, and its VAAPI options are limited. Meanwhile a
desktop PC with an RTX 5090 sits on the same LAN with a very fast NVENC AV1
encoder — but it runs Windows, is only powered on some of the time, and
shouldn't need to be part of TA's docker deployment.

Goal: let that PC (and potentially other hosts later) pull downscale jobs
from TA, encode them on its own hardware, and hand the results back — while
TA remains the single source of truth for the queue, the review flow, and
the library.

## Architecture in one paragraph

A **pull-based worker**. The remote host runs a small standalone script (the
"sister app") that polls TA's HTTP API: claim the oldest queued job,
download the source file, encode it with its own HandBrake/encoder
settings, rewrap the result to MP4, upload it into the job's existing
`tmp_file_path`, and report completion. TA flips the job to
`pending_review`, and everything downstream — the review UI, the compare
slider, accept/reject, cache-sweep protection of tmp files — works exactly
as it does for locally encoded jobs. A remote worker is just another way a
job travels from `queued` to `pending_review`.

```
  TubeArchivist (Pi / Unraid)                Gaming PC (Windows + 5090)
 ┌───────────────────────────┐              ┌──────────────────────────┐
 │ ES: ta_downscale queue    │   claim      │ worker script (WSL or    │
 │ celery: local encoder     │◄─────────────│ native Windows Python)   │
 │ nginx + django API        │   source ───►│                          │
 │                           │◄─── progress │ HandBrakeCLI (nvenc_av1) │
 │ review UI (unchanged)     │◄─── result   │                          │
 └───────────────────────────┘              └──────────────────────────┘
```

## Key decisions

**Pull, not push.** TA never needs to know a worker's address, whether it is
online, or how many there are. A powered-off PC simply means jobs wait in
the queue (where the local encoder can still pick them up). The rejected
alternative — running the PC as a real celery worker against the Pi's Redis
with media shared over SMB — was discarded: celery is unsupported on
Windows, it would expose Redis on the LAN, and cross-host path mapping is
brittle.

**The worker owns its encoder configuration.** TA owns the *intent* of a job
(which video, target height, a rough quality number). The worker knows its
own hardware and maps that intent onto its configured encoder
(`HandBrakeCLI -e nvenc_av1 -q …` on the 5090 — note HandBrake prefixes
its NVENC names where ffmpeg suffixes them, so the recorded encoder
string is `nvenc_av1`, not ffmpeg's `av1_nvenc`). Quality numbers are
not portable between
encoder families anyway — CRF for libsvtav1, ICQ for VAAPI, and CQ for
NVENC are different scales — so pretending TA can centrally pick exact
settings for arbitrary hardware would be a lie. What the worker *actually
ran* is reported back and recorded on the job.

**Record the full ffmpeg argv.** Both local and remote encodes persist the
exact ffmpeg command line on the job doc, and `accept()` copies it into the
video's `downscale` block. With heterogeneous encoders, the argv is the
only unambiguous record of what produced a file; the high-level
encoder/quality/preset fields remain for display and filtering.

**Same queue, shared fairly.** Local celery dispatch and remote claims draw
from the same `ta_downscale` queue and race under the same Redis dispatch
lock — first claim wins. Remote jobs do not count against
`downscale_max_concurrent`, which exists to protect the TA host's own CPU.
Setting `downscale_max_concurrent = 0` becomes the way to disable local
encoding entirely (remote-only mode); today `0` is accidentally treated as
"unlimited", which gets fixed as part of this work.

**Leases, because remote workers die silently.** A claimed job carries a
worker name and a heartbeat timestamp. Heartbeats double as progress
updates and as the channel for cancel signals. A reaper requeues jobs whose
heartbeat has gone stale, so a crashed or powered-off PC returns its job to
the queue automatically. TA restarts must *not* requeue live remote jobs —
they survive a TA restart just fine — which requires a change to the
existing startup auto-resume sweep.

## Job lifecycle (remote path)

```
queued ──claim──► running (worker=X, heartbeats)
                    │
                    ├─ upload + finish ──► pending_review ──► accept/reject
                    ├─ fail report ──────► failed ──► retry ──► queued
                    ├─ user cancel ──stop via heartbeat──► deleted
                    └─ heartbeat stale ──reaper──► queued (re-claimable)
```

## Delivery phases

1. **ffmpeg argv persistence** — standalone value for local encodes;
   trivial, do first. (ta-server.md §"Full ffmpeg argv")
2. **TA worker API** — claim / source / heartbeat / result / finish / fail
   endpoints, doc schema additions, reaper, startup-sweep and concurrency
   fixes. (ta-server.md)
3. **The worker script** — single-file Python app for the gaming PC,
   driving native `HandBrakeCLI.exe` with NVENC, plus `ffmpeg.exe` to
   rewrap the result to MP4. (worker.md)
4. **Polish** — unified progress display in the queue UI, worker visibility
   (which worker holds which job), maybe multiple simultaneous jobs per
   worker.

## Non-goals (for now)

- WAN operation, TLS, scoped credentials — this is a LAN deployment using
  the existing DRF token auth.
- Central per-worker encoder configuration in the TA UI.
- Remote *download* or other task types — this is only about downscaling.
