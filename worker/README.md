# TubeArchivist remote downscale worker

Single-file sister app that claims downscale jobs from a TubeArchivist
instance and encodes them on local hardware.

**Setting this up on a real machine for the first time? Follow
[docs/remote-downscale/windows-host-setup.md](../docs/remote-downscale/windows-host-setup.md)**
— it covers what to verify, in what order. The notes here are just the
short version.

Full design: [docs/remote-downscale/worker.md](../docs/remote-downscale/worker.md)
(and [ta-server.md](../docs/remote-downscale/ta-server.md) for the API
it talks to).

## Setup

Two example configs, one per deployment target — same script either way,
only `worker.toml` differs:

- **`worker.nvenc_windows.toml.example`** — Windows (or WSL invoking
  Windows binaries) + NVENC hardware AV1. The original/production target;
  see [windows-host-setup.md](../docs/remote-downscale/windows-host-setup.md).
- **`worker.cpu.toml.example`** — native Linux + software AV1
  (`svt_av1`), for hosts with no hardware AV1 encoder (e.g. a Raspberry
  Pi fleet). Unverified against real hardware — see the encoder/preset
  notes in the file itself before trusting the values.

```
pip install -r requirements.txt
cp worker.nvenc_windows.toml.example worker.toml   # or worker.cpu.toml.example
# edit worker.toml: server url/token, worker name, temp_dir, encoder
python ta_downscale_worker.py
```

Runs in a loop until stopped with Ctrl-C. No daemon/service wrapper yet —
v1 is "run it in a terminal when the PC is on" (Task Scheduler/NSSM can
come later, see worker.md).

## What it needs

One Python dependency (`requests`, Python 3.11+) and three external
binaries:

- **`HandBrakeCLI`** — encodes the source to `.mkv`. HandBrake, rather
  than raw ffmpeg, because it preserves HDR10 static metadata through an
  NVENC encode automatically.
- **`ffmpeg`** — stream-copies that `.mkv` into the `.mp4` TubeArchivist
  stores. A rewrap, not a re-encode: no quality cost, no GPU time. TA
  cannot store MKV (its filesystem scanner only sees `*.mp4` and deletes
  indexed videos it can't find), so this step is not optional.
- **`ffprobe`** — reads HDR metadata off the source and the rewrapped
  result, and logs whether anything was lost in between.

`temp_dir` needs room for all three files at once — source, encode, and
rewrap coexist until the job finishes. Budget roughly 3× the largest
source.

## WSL

NVENC is not available inside WSL2, so under WSL the script must invoke
the **Windows** `.exe` builds of all three binaries; it handles the
`wslpath -w` conversion for paths it hands them. Point `temp_dir` at a
Windows-visible path (e.g. `/mnt/c/ta-work`).

Native Windows Python avoids the translation entirely and is the simpler
starting point.

None of this applies to a native Linux deployment (e.g. `worker.cpu.toml.example`)
— the script's WSL detection (`_is_wsl()`) is only true when `/proc/version`
mentions Microsoft, so on a Pi or any other native Linux box the path
translation is simply never invoked.
