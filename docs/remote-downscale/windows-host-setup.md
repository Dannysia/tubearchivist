# Remote downscale — Windows worker host setup & verification

Status: **run against real hardware since 2026-08-14** (RTX 5090, WSL2 +
Windows binaries). §1-9 have all been walked through and corrected where
the original guesses were wrong (§3 in particular — the original example
command used a flag that silently didn't downscale, see the callout
there). §11 has the settings that actually shipped and why.

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
  -e nvenc_av1 -q 24 --height 1080 --non-anamorphic `
  --start-at seconds:60 --stop-at seconds:60
```

Repeat for 22 / 26 / 28, compare size and appearance, pick one.

> **Anamorphic trap — use `--non-anamorphic`, not `--keep-display-aspect`.**
> `--keep-display-aspect` only takes effect under `--custom-anamorphic`
> and is a **silent no-op** otherwise — confirmed on real hardware
> 2026-08-14. With just `--height` set, it leaves storage width at the
> *source's* width and fakes the target aspect ratio with a non-1:1
> pixel aspect ratio instead of actually resizing: a 4K source
> "downscaled" to 720p this way came out `3840x720`, PAR `1:3` — three
> times the real pixel count of a true 720p frame, all cost and no
> savings. `--non-anamorphic` forces PAR 1:1, which is what makes an
> unset `--width` actually auto-compute a proportional value. Every job
> the worker produced before this was caught was silently anamorphic;
> none had been accepted into the library yet when it was found. Verify
> with `ffprobe -show_entries stream=width,height,sample_aspect_ratio`
> on the output before trusting any new preset/quality trial.

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

## 6. Verify the HDR round trip — **CLOSED, verified 2026-08-15**

**Result: HDR10 (PQ) and HLG both survive the full pipeline intact.**
Tested against real HDR sources from
[haasn/hdr-tests](https://github.com/haasn/hdr-tests) — the mpv/libplacebo
project's HDR tone-mapping test corpus, a convenient source of genuinely
HDR-tagged clips for exactly this kind of verification. Full results and
the specific clips used are in §11. The steps below are kept as the
general verification procedure for testing *other* sources later — the
open question they were written to resolve is answered.

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
- The **HDR rewrap question** in §6 — the reason this document exists —
  is now **closed**, see §11. (Two earlier candidates downloaded via
  yt-dlp both turned out to be SDR on inspection, unrelated to this
  worker; genuinely HDR-tagged test content was found afterward.)

---

## 11. Final tuned settings (production, as of 2026-08-14)

The values actually running in `worker.toml` / `worker2.toml`, and why,
superseding the guesses in §3-4 above:

| Setting | Value | Why |
|---|---|---|
| `encoder` | `nvenc_av1_10bit` | 5.1% smaller than `nvenc_av1` at identical `-q` on a real 8-bit source (A/B tested) — 10-bit reduces quantization error per plane independent of source bit depth, no playback-compatibility cost since HandBrake's preset/tune lists are identical between the two. |
| `preset` | `slowest` | See below. |
| `quality` (`-q`) | `32` | Tuned against real 720p game-capture content (flat/high-contrast UI, worst case for AV1 CQ). See table below — **content-dependent, re-trial for other content types.** |
| audio | stream-copy (`-E copy` + `--audio-copy-mask` + `--audio-fallback av_aac`) | Without it, HandBrake silently transcodes already-lossy Opus to AAC for no size benefit — pure quality loss. |
| decode | `--enable-hw-decoding nvdec` | Moves decode off the CPU onto NVDEC. ~15% slower wall-clock solo (engine handoff overhead), but frees the CPU for concurrent workers — output is byte-identical either way, this is a CPU-headroom trade, not a quality one. |
| `--non-anamorphic` | always | **Not optional.** See the trap called out in §3 — without it, output isn't actually downscaled. |

### Preset: `slow` → `slowest`

HandBrake does **not** expose ffmpeg's `av1_nvenc` preset naming
(`p1`-`p7`) for `nvenc_av1` at all — confirmed via
`HandBrakeCLI --encoder-preset-list=nvenc_av1` on this machine, which
lists exactly seven named tiers: `fastest / faster / fast / medium /
slow / slower / slowest`. There is no `p6`/`p7` to target directly;
`slowest` is simply the ceiling of that list.

The original tuning pass (2026-08-13) A/B'd `slow` against
`slower`/`slowest` on a real game-capture clip and found `<0.2%` size
difference for `+17%` encode time — judged not worth it *when
optimizing for wall-clock throughput*. Changed to `slowest` on
2026-08-14: this is a hardware encode with GPU headroom to spare, and
the constraint isn't wall-clock time, so the right call is to take
whatever quality the ceiling preset offers even when the measured delta
is small, rather than to leave quality on the table to save a nearly-free
17%.

### `-q` trial results (720p, game-capture content — NOT universal)

60-second-clip trial against a real 720p Factorio gameplay source
(~1.26 Mbps video, flat-shaded/high-contrast UI — a worst case for AV1
NVENC's CQ scale):

| `-q` | size vs. source | visual result |
|---|---|---|
| 24 (original guessed default) | **+73% to +144%** | shipped on the first bad batch — never trust an untested default |
| 28 | ~95% | barely smaller, no real savings |
| **32** | **-30%** | clean — UI text fully legible, no visible blocking — **current default** |
| 36 | -47% | still clean, more aggressive |
| 40 | -47%+ | mild blockiness on dark textures |

Confirmed still content-dependent in production: 11 of 12 real library
jobs at `q=32` shrank 56-86%, but one high-motion trailer
("Factorio - Trailer 2014") still *grew* +13.7% even after the
anamorphic fix. Live-action / high-motion content has not had its own
trial yet — re-run this same process (§3) before trusting `q=32` there.

For a broader (non-project-specific) reference point on where other
NVENC AV1 deployments land — HandBrake publishes no official NVENC
numbers, so this is community precedent, not documented guidance —
see the CQ-value research summarized in this repo's chat history around
2026-08-14: a real deployed tool ([jellyfin-encoder]) uses AV1 CQ 28
(archival-leaning) / 35 (medium) / 45 (max savings) at a 720p target;
archival-focused ffmpeg guides for `av1_nvenc` lean toward CQ 24-25.
Our `q=32` sits between jellyfin-encoder's medium and archival tiers.

[jellyfin-encoder]: https://github.com/GeiserX/jellyfin-encoder

### Rejected/inconclusive experiments (don't re-try without new evidence)

- **`--multi-pass`**: byte-identical output with/without it on a real
  clip, for NVENC AV1 CQ mode. No-op, not added.
- **`-x spatial-aq=1:temporal-aq=1:aq-strength=8`**: didn't error, but
  changed output size (+7.6%) in a way that couldn't be distinguished
  from HandBrake mishandling unsupported encopts for NVENC vs. a real
  AQ effect. Not adopted without a clearer signal.

### HDR round trip — full results (closes §6, 2026-08-15)

Test source: [haasn/hdr-tests](https://github.com/haasn/hdr-tests), the
mpv/libplacebo project's HDR tone-mapping test corpus — a git repo of
short clips deliberately tagged with real HDR10/HLG metadata, useful
here purely as a source of genuinely-HDR content to verify against
(nothing else about that repo is relevant to this project). Cloning it
needs `git-lfs` for four specific files (`landing_*.mkv`,
`tonemap_flicker.mkv`); everything else is plain git and works without
it.

Both real-hardware trials ran the exact production command
(`nvenc_av1_10bit`, `-q 32`, `--encoder-preset slowest`,
`--enable-hw-decoding nvdec`, `--non-anamorphic`, `-E copy` audio) end
to end: HandBrakeCLI encode → MKV → ffmpeg stream-copy remux → MP4,
verified with `ffprobe` at every stage.

**HDR10/PQ** — `01. Black Clipping_1_HDR10.mp4` (HEVC, 3840x2160,
`smpte2084`/`bt2020`, real Mastering-display + Content-light-level SEI):

| | source | output |
|---|---|---|
| `color_transfer` / `color_primaries` | smpte2084 / bt2020 | **identical** |
| Mastering display metadata | r(0.68,0.32) g(0.265,0.69) b(0.15,0.06) | **identical**, at both container level and bitstream/SEI level |
| Content light level | max_cll=1000, max_fall=400 | **identical** (`max_content=1000, max_average=400`), both levels |
| size | 47.4MB | 5.15MB (**-89.1%**) |

Confirms the design's core bet (§0): HandBrake writes NVENC's HDR10
static metadata into the MKV container, and the ffmpeg stream-copy
remux to MP4 carries it through without loss, on the ffmpeg build in
use here (gyan.dev 9.0-full). If you're on a different/older ffmpeg
build and see it dropped, §6's steps still apply.

**HLG** — `snow-fades.mp4` (HEVC, 3840x2160, `arib-std-b67`/`bt2020`,
AAC audio):

| | source | output |
|---|---|---|
| `color_transfer` / `color_primaries` / `color_space` | arib-std-b67 / bt2020 / bt2020nc | **identical** |
| static metadata | none (expected — HLG carries none by design) | none |
| resolution | 3840x2160 | 1280x720, PAR 1:1 — clean 16:9, matches naive scaling exactly |
| audio | AAC 128884 bps | AAC 128839 bps (copy, negligible container rounding) |
| size | 3.37MB | 1.47MB (**-56.4%**) |

A second HLG-named file in the same repo, `Grayscale BT.2100 HLG.mkv`,
was checked but **not** used for this test — despite the name, its
actual `color_transfer` tag is `bt2020-10`, not `arib-std-b67`; treat
its filename as describing test *intent*, not a reliable tag to probe
for. A third file, `snow.hevc`, is a raw HEVC elementary stream with
malformed/absent packet timestamps — ffmpeg's raw demuxer can't
establish real duration from it (`c:v copy` remux fails outright;
re-encoding it gets exactly one usable frame). Not pursued further:
it's a pathological test asset, not a shape of input this worker will
ever see from TA (sources always arrive as properly-muxed files).

**Side finding: HandBrake's auto-crop is on by default.** The HDR10
test clip has real ~28-56px black borders (confirmed via
`ffmpeg -vf cropdetect`); HandBrake trimmed them before scaling, so
`--height 720` produced `1314x720` instead of the naively-expected
`1280x720` for a 16:9 4K source. This is desirable behavior — no bits
spent encoding padding — but means output width won't always match a
plain `source_width * 720 / source_height` calculation when a source
has letterboxing. Not a recurrence of the anamorphic bug (§3): PAR
stayed 1:1 in both cases, this is a genuinely different frame size
after real content was cropped, not a fake aspect ratio. Worth knowing
before treating an unexpected output width as a red flag.
