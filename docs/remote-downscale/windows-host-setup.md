# Remote downscale — Windows worker host setup & verification

Status: **written against the shipped code, never run on real hardware.**

This is the runbook for bringing the worker up on the gaming PC (Windows
+ RTX 5090) for the first time. It exists because a handful of things in
the worker were chosen from documentation rather than from a real
install, and they need confirming on the actual machine before a large
unattended run.

Read [worker.md](worker.md) for the design and
[ta-server.md](ta-server.md) for the API. This document is only the
hands-on part.

**Work through §1–§6 in order.** Each one either passes or gives you a
specific value to put in `worker.toml`. §7 is the first real job. §8 is
what to do when something looks wrong.

---

## 0. What the worker actually runs

Three binaries per job, which is worth understanding before debugging
any of them:

| Tool | Role | Why it's this one |
|---|---|---|
| `HandBrakeCLI` | encode source → `.mkv` | preserves HDR10 static metadata through an NVENC encode automatically |
| `ffmpeg` | stream-copy `.mkv` → `.mp4` | TubeArchivist is MP4-only; this is a rewrap, **not** a re-encode |
| `ffprobe` | read HDR metadata before/after | confirms the rewrap didn't drop anything |

The MKV detour is not cosmetic. HandBrake's own docs say that with
NVENC, HDR10 metadata is written **only into the container, not the
bitstream** — so the container it lands in matters, and MKV is the one
that behavior is documented for. TA, meanwhile, cannot store MKV: its
filesystem scanner only sees `*.mp4` and **deletes indexed videos it
can't find**, reindex rebuilds `media_url` with a hardcoded `.mp4`, and
subtitle paths are derived by string-replacing `".mp4"`. Encoding to MKV
and rewrapping to MP4 is what satisfies both constraints.

**Whether the rewrap actually carries HDR10 metadata across is the one
open question in this design** (§6). It's been verified for
bitstream-carried metadata but *not* for the container-carried metadata
NVENC produces, because that needs a real NVENC encode.

---

## 1. Install the binaries

- **HandBrakeCLI** — <https://handbrake.fr/downloads2.php>. AV1 NVENC
  needs **HandBrake 1.7+**; 1.10+ is preferable (it refined the NVENC
  constant-quality range, so older guides' numbers may not transfer).
- **ffmpeg + ffprobe** — a full build, e.g. gyan.dev or BtbN. Both
  binaries ship side by side, which is why `worker.toml` only asks for
  `ffmpeg_path`.
- **Python 3.11+** (`tomllib` is stdlib from 3.11) and `requests`.

Confirm all three resolve:

```powershell
HandBrakeCLI --version
ffmpeg -version
ffprobe -version
python --version
```

If they aren't on `PATH`, use absolute paths in `worker.toml` — the
worker never assumes `PATH`.

### WSL or native Windows?

Either works. **NVENC is not available inside WSL2** — NVIDIA's WSL
driver exposes CUDA but not the encode engine — so under WSL the worker
must invoke the **Windows** `.exe` binaries, which it does by translating
paths with `wslpath -w` automatically. Requirements if you go that way:

- `temp_dir` must be on a Windows-visible path (e.g. `/mnt/c/ta-work`)
- `handbrake_path` / `ffmpeg_path` point at `.exe` files

Native Windows Python removes the translation entirely. **Start native
unless you have a reason not to** — one less variable while verifying.

---

## 2. Confirm the encoder exists

```powershell
HandBrakeCLI --encoder-list
```

Look for `nvenc_av1` in the video encoder list.

> **Naming trap.** HandBrake *prefixes* NVENC encoders (`nvenc_av1`,
> `nvenc_h265`, `nvenc_h264`); ffmpeg *suffixes* them (`av1_nvenc`,
> `hevc_nvenc`). `worker.toml` takes HandBrake's spelling. The value you
> put here is recorded verbatim on every job and shown in TA's UI, which
> maps both conventions to the same label.

If `nvenc_av1` is absent: HandBrake is older than 1.7, or the GPU/driver
isn't being detected. AV1 NVENC needs Ada Lovelace or newer — a 5090
qualifies comfortably.

---

## 3. Pin down preset, tune, and quality

**These three values in the shipped `worker.toml.example` are guesses.**
Replace them with real ones:

```powershell
HandBrakeCLI --encoder-preset-list=nvenc_av1
HandBrakeCLI --encoder-tune-list=nvenc_av1
```

Set `preset` to a listed value. Leave `tune` commented out unless a
listed tune is clearly what you want — an unlisted value makes HandBrake
exit non-zero, which is loud but wastes a job.

**Quality** is HandBrake's `-q`. There is no universal right answer, and
the AV1 NVENC scale is not the same as x265 CRF. Encode one 60-second
clip at a few values and look at them:

```powershell
HandBrakeCLI -i "C:\some\source.mp4" -o "C:\ta-work\q24.mkv" `
  -e nvenc_av1 -q 24 --height 1080 --keep-display-aspect `
  --start-at seconds:60 --stop-at seconds:60
```

Repeat for 22 / 26 / 28, compare size and appearance, pick one.

> **`quality` must be a whole number.** HandBrake accepts fractional
> `-q` (22.5 is idiomatic for x265), but TA stores quality as an integer
> and rejects anything else. The worker refuses to start on a fractional
> value rather than failing a job after encoding it — if it exits
> immediately complaining about `quality`, this is why.

---

## 4. Write `worker.toml`

Copy `worker.toml.example` next to the script and fill it in:

```toml
[server]
url = "http://tubearchivist.local:8000"
token = "…"                  # TA → Settings → API

[worker]
name = "gaming-pc"           # unique per worker; identifies job ownership
temp_dir = "C:\\ta-work"     # or /mnt/c/ta-work under WSL
poll_interval = 30
heartbeat_interval = 10      # must stay well under the server's 60s lease

[encode]
ffmpeg_path = "ffmpeg.exe"
handbrake_path = "HandBrakeCLI.exe"
encoder = "nvenc_av1"
preset = "…"                 # from §3
quality = 24                 # from §3, whole number
extra_args = []
```

Two sizing notes:

- **`temp_dir` needs room for three files at once** — the source, the
  MKV encode, and the MP4 rewrap all coexist until the job finishes.
  Budget roughly 3× your largest source. Put it on the NVMe.
- **`heartbeat_interval` is not currently validated.** The server reaps
  any lease it hasn't heard from in **60 seconds**. Setting this at or
  above 60 means every job gets reaped mid-encode and silently requeued
  — an infinite re-encode loop at full GPU load with nothing marked
  failed. Keep it at 10.

Sanity-check the file parses before running anything real:

```powershell
python -c "import tomllib;print(tomllib.load(open('worker.toml','rb'))['encode'])"
```

---

## 5. First contact with TA

Start it:

```powershell
python ta_downscale_worker.py --config worker.toml
```

Expected on an empty queue:

```
[hh:mm:ss] worker 'gaming-pc' starting, polling http://tubearchivist.local:8000
```

…then silence, polling every `poll_interval` seconds.

| What you see | What it means |
|---|---|
| `claim failed: 401 …` | bad or non-admin token |
| `claim failed: 404 …` | wrong `url`, or nginx not routing `/api/downscale/worker/` |
| `claim failed: … Connection refused` | TA unreachable from this box; check firewall/DNS |
| immediate exit re: `quality` | §3 — fractional value |
| immediate exit re: missing key | a required `worker.toml` field is absent |

A failed claim is never fatal — it logs and retries next poll. If it's
looping on 401, stop it and fix the token; it will otherwise sit there
forever.

---

## 6. Verify the HDR round trip ← **the important one**

Do this **before** a large run, on a genuinely HDR source. Find one:

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=color_transfer,color_primaries -of default=nw=1 "C:\path\video.mp4"
```

`color_transfer=smpte2084` (HDR10/PQ) or `arib-std-b67` (HLG) means
you've got one.

Now check for the static metadata specifically. **Both of these matter,
and they report different things:**

```powershell
# container-level (what HandBrake writes for NVENC)
ffprobe -v error -select_streams v:0 -show_streams -of json "C:\path\video.mp4" | findstr side_data_type

# bitstream-level / SEI (what software encoders write)
ffprobe -v error -select_streams v:0 -show_frames -read_intervals "%+#1" -of json "C:\path\video.mp4" | findstr side_data_type
```

You're looking for `Mastering display metadata` and
`Content light level metadata`. **A source can have them in either
place** — checking only `-show_streams` misses every SEI-carried file,
which is most HDR that didn't come from a hardware encoder.

Then run one real job through the worker and read its log. The worker
probes automatically and tells you the outcome:

```
video1: source has Content light level metadata, Mastering display metadata
video1: HDR10 static metadata survived the remux (Content light level …)
```

or

```
video1: WARNING - HDR10 static metadata lost in the remux to mp4: …
```

**If you see the WARNING**, the MKV→MP4 rewrap is dropping
container-level metadata on your ffmpeg build. That's the scenario this
design couldn't rule out in advance. Options, roughly in order:

1. **Update ffmpeg.** Writing `mdcv`/`clli` boxes into MP4 is relatively
   recent; an older build may simply not do it. Try a current gyan.dev
   or BtbN build first — cheapest fix by far.
2. **Add the metadata explicitly** to the remux via
   `-metadata:s:v:0 …`, once you can see the exact values ffprobe
   reports on the MKV.
3. **Reconsider the container**, which is a much larger change — TA
   would need real MKV support (see §0), touching the filesystem
   scanner, reindex, subtitles, and metadata embedding. Don't go here
   without a strong reason.

Whichever way it lands, **record the answer** — it resolves the one
genuinely open question in this design.

> **Losing static metadata is not catastrophic.** It's tone-mapping
> guidance (how bright the mastering display was), not the colour
> definition itself. Transfer characteristics and colour primaries —
> the tags whose loss causes visibly washed-out playback — travel with
> the video stream and are not at risk here. HLG content carries no
> static metadata at all by design, so it's unaffected either way.

---

## 7. First real job, end to end

Queue a single downscale in TA's UI and watch both sides.

Expected worker log, in order:

```
claimed <id> -> 720p
encoding <id>: HandBrakeCLI.exe -i … -e nvenc_av1 -q 24 --height 720 …
encoded <id>, remuxing to mp4
remuxing: ffmpeg -v error -y -i …out.mkv -map 0:v:0 -map 0:a? -c copy -movflags +faststart …out.mp4
uploading <id>
finishing <id>
done: <id>
```

Check as it runs:

- **GPU is actually being used** — Task Manager → Performance → GPU →
  the **Video Encode** graph (not 3D). Flat at 0% means it fell back to
  software; stop and re-check §2.
- **Progress moves in TA's queue UI.** If it sits at 0% the whole time
  the encode is running, HandBrake's progress wording doesn't match the
  worker's regex (`task N of M, XX.XX %`). Harmless — the encode is
  fine, only the percentage is blind — but worth reporting so the
  pattern can be corrected.
- **Three files appear in `temp_dir`** and all disappear when the job
  finishes. Leftovers mean cleanup isn't matching what's written.

Then accept the result in TA and confirm the video still plays in TA's
own player. It should: the stored file is MP4 with `+faststart`.

---

## 8. Troubleshooting

**Encode fails immediately, non-zero exit.** The worker reports the
HandBrake output tail to TA, so read the job's message in the queue UI.
Almost always an invalid `preset`/`tune`/`encoder` — back to §2/§3.

**`remux exited …` in the job message.** ffmpeg couldn't rewrap. Check
`ffmpeg_path` and run the exact command from the log by hand.

**Jobs flicker between `queued` and `running` forever.** The lease is
being lost. Check `heartbeat_interval` < 60 (§4) and the LAN link.

**Worker exits on a `PermissionError` during cleanup.** Windows won't
delete a file another process still holds. Usually means HandBrake or
ffmpeg is still running — check Task Manager for an orphan and kill it.

**Jobs claimed but nothing encodes, no error.** Check `handbrake_path`
resolves. A wrong path currently produces one log line and moves on,
re-downloading the source each pass — it does not mark jobs failed.
Watch for repeated `claimed <same id>` lines.

**Everything works but TA shows the encoder oddly.** Expected: TA records
whatever string you configured (`nvenc_av1`), and the UI maps both
HandBrake and ffmpeg spellings to `AV1 (Hardware - NVENC)`.

---

## 9. Leaving it running

Once §7 passes cleanly on a handful of jobs:

- Queue a larger batch and watch the first few, then let it run.
- The worker takes **one job at a time** by design. The 5090 could
  manage several NVENC sessions, but one keeps the worker trivial.
- It keeps no state between jobs — everything lives on the server, so
  killing and restarting it at any point is safe. On startup it sweeps
  `temp_dir` of anything left behind.
- For autostart later: Task Scheduler "at logon" running `pythonw.exe
  ta_downscale_worker.py` (native) or `wsl.exe -e python3 …` (WSL). Not
  needed for a first run — a terminal window is the whole UI.

## 10. Things still unverified after this runbook

Worth stating plainly, so they aren't mistaken for tested behavior:

- `worker/ta_downscale_worker.py` has **no automated tests**. Everything
  in it has been verified by hand or by ad-hoc scripts.
- The HandBrake **progress regex** has never been matched against real
  HandBrakeCLI output (§7).
- **Windows file-locking behavior** during cleanup and the `wslpath`
  translation path are both reasoned-about, not exercised.
- The **HDR rewrap question** in §6 — the reason this document exists.
