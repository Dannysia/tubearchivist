# TubeArchivist remote downscale worker

Single-file sister app that claims downscale jobs from a TubeArchivist
instance and encodes them locally. Full design:
[docs/remote-downscale/worker.md](../docs/remote-downscale/worker.md) (and
[ta-server.md](../docs/remote-downscale/ta-server.md) for the API it talks
to).

## Setup

```
pip install -r requirements.txt
cp worker.toml.example worker.toml
# edit worker.toml: server url/token, worker name, temp_dir, encoder
python ta_downscale_worker.py
```

Runs in a loop until stopped with Ctrl-C. No daemon/service wrapper yet —
v1 is "run it in a terminal when the PC is on" (Task Scheduler/NSSM can
come later, see worker.md).

Under WSL invoking `ffmpeg.exe`/`ffprobe.exe` for NVENC access, point
`temp_dir` at a Windows-visible path (e.g. `/mnt/c/ta-work`); the script
handles the `wslpath -w` conversion for paths it hands to those binaries.
