![Tube Archivist](assets/tube-archivist-front.jpg?raw=true "Tube Archivist Banner")

# Tube Archivist — personal fork

A personal fork of **[tubearchivist/tubearchivist](https://github.com/tubearchivist/tubearchivist)**
by [bbilly1](https://github.com/bbilly1), which is where all the credit
for this project belongs. It is developed and run locally on a Raspberry
Pi 5, with an eventual move to Unraid.

This fork has diverged significantly and there is no intent to contribute
the changes back. Anything below describes *this* fork; for everything it
has not changed, upstream's [documentation](https://docs.tubearchivist.com/)
is still the reference, including the [FAQ](https://docs.tubearchivist.com/faq/)
and API docs. Be aware that the parts this fork has changed — manual
import in particular — no longer match what those docs describe.

* [What this fork adds](#what-this-fork-adds)
* [Running it](#running-it)
* [Build and deploy](#build-and-deploy)
* [Development](#development)
* [Common errors](#common-errors)
* [Upstream](#upstream)

------------------------

## What this fork adds

**Downscaling.** An ffmpeg based downscale pipeline with a review queue:
queue a video or a whole channel at a target height, encode it, then
accept or reject the result before it replaces the original. Savings are
reported per channel on the channel about page and archive wide on the
dashboard, split by encoder. Videos can be filtered by downscale state
and codec. Design notes in [docs/downscale-dedup](docs/downscale-dedup/README.md)
and [docs/downscale-hdr](docs/downscale-hdr/README.md).

**Remote downscale workers.** A single file sister app in [worker/](worker/README.md)
that claims downscale jobs over the API and encodes them on other
hardware, e.g. a Windows box with NVENC. See [docs/remote-downscale](docs/remote-downscale/README.md).

**Manual import from the web UI.** Upload media and sidecar files into the
import folder from the settings page, and generate an `info.json` for a
video that is no longer on YouTube, rather than hand writing one and
copying it in.

**Metadata history.** Every field a refresh changes is recorded in a
`ta_history` index, so a view count or title can be followed over time.
See [docs/metadata-history](docs/metadata-history/README.md).

**Task notification log.** What each background task did, kept in a
`ta_log` index and readable under settings → logs long after the
on-screen message has gone. Only runs that did something are recorded,
so an overnight failure is not buried under hundreds of "nothing to do".
Entries are pruned on a daily schedule, seven days by default.

**More stats.** Per channel totals on the channel about page, channel list
sorting by video count, size, duration, watch progress or archive dates,
and downscale savings on the dashboard.

**Build identity.** The footer reports the upstream release this is based
on plus the build actually running, e.g. `v0.5.12 · 1c06370d · Aug 26,
2026, 5:29 PM`, so a deploy can be confirmed at a glance.

## Running it

The stack is upstream's — TubeArchivist, Elasticsearch and Redis — and
every environment variable below behaves as upstream documents it. Around
2GB of memory suffices for a small install, 4GB for a larger one.

### TubeArchivist

| Environment Var               | Value | Required |
| ----------------------------- | ----- | -------- |
| TA_HOST                       | Server IP or hostname `http://tubearchivist.local:8000` | Required |
| TA_USERNAME                   | Initial username when logging into TA | Required |
| TA_PASSWORD                   | Initial password when logging into TA | Required |
| ELASTIC_PASSWORD              | Password for ElasticSearch | Required |
| REDIS_CON                     | Connection string to Redis | Required |
| TZ                            | Set your timezone for the scheduler | Required |
| TA_PORT                       | Overwrite Nginx port | Optional |
| TA_BACKEND_PORT               | Overwrite container internal backend server port | Optional |
| TA_ENABLE_AUTH_PROXY          | Enables support for forwarding auth in reverse proxies | [Read more](https://docs.tubearchivist.com/configuration/forward-auth/) |
| TA_AUTH_PROXY_USERNAME_HEADER | Header containing username to log in | Optional |
| TA_AUTH_PROXY_LOGOUT_URL      | Logout URL for forwarded auth | Optional |
| ES_URL                        | URL That ElasticSearch runs on | Optional |
| ES_DISABLE_VERIFY_SSL         | Disable ElasticSearch SSL certificate verification | Optional |
| ES_SNAPSHOT_DIR               | Custom path where elastic search stores snapshots for master/data nodes | Optional |
| HOST_GID                      | Allow TA to own the video files instead of container user | Optional |
| HOST_UID                      | Allow TA to own the video files instead of container user | Optional |
| ELASTIC_USER                  | Change the default ElasticSearch user | Optional |
| TA_LDAP                       | Configure TA to use LDAP Authentication | [Read more](https://docs.tubearchivist.com/configuration/ldap/) |
| DISABLE_STATIC_AUTH           | Remove authentication from media files, (Google Cast...) | [Read more](https://docs.tubearchivist.com/installation/env-vars/#disable_static_auth) |
| TA_AUTO_UPDATE_YTDLP          | Configure TA to automatically install the latest yt-dlp on container start | Optional |
| DJANGO_DEBUG                  | Return additional error messages, for debug only | Optional |
| TA_LOGIN_AUTH_MODE            | Configure the order of login authentication backends (Default: single) | Optional |

Both `TA_PASSWORD` and `ELASTIC_PASSWORD` can be suffixed with `_FILE` to
pass them in as secrets.

### Elasticsearch

| Environment Var  | Value | Required |
| ---------------- | ----- | -------- |
| ELASTIC_PASSWORD | Matching password `ELASTIC_PASSWORD` from TubeArchivist | Required |
| http.port        | Change the port ElasticSearch runs on | Optional |

## Build and deploy

This fork publishes to a private GHCR package rather than Docker Hub, so
none of upstream's `:latest` / `:unstable` tags apply here. There is no
update path from this fork to an upstream image or back.

### CI, the image Unraid pulls

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs on every
push to `develop`: lint, tests, then a `linux/amd64` build pushed to
`ghcr.io/dannysia/tubearchivist` tagged `mainline` and `sha-<commit>`.
That is the only thing that should ever write `:mainline` — building that
tag by hand from a different architecture is how an amd64 host ends up
pulling an arm64 image it cannot run.

GHCR packages default to private, so Unraid needs a pull only login of its
own, using a PAT scoped to `read:packages`:

```shell
docker login ghcr.io -u dannysia --password-stdin
```

Then set Unraid's **Repository** field to:

```
ghcr.io/dannysia/tubearchivist:mainline
```

### Local, on the Pi

[`local_deploy.sh`](local_deploy.sh) builds the working tree — committed
or not — and deploys it to the local stack. It never pushes anywhere, and
it tags the previous image first so a bad deploy is one command to undo.

```shell
./local_deploy.sh           # build, tag a rollback point, deploy, verify
./local_deploy.sh build     # build the image only
./local_deploy.sh rollback  # put the previous image back
./local_deploy.sh status    # what is running right now
```

It stamps the build's commit into the image, marking it `-dirty` when
tracked files have uncommitted changes, which is what the footer reports.

## Development

There is no python environment on the host. [`run_tests.sh`](run_tests.sh)
runs pytest in a throwaway container built from the deployed image, with
the working tree mounted and its own throwaway redis. The running stack is
never touched.

```shell
./run_tests.sh                 # whole suite
./run_tests.sh backend/common  # subset, args are passed to pytest
./run_tests.sh lint            # black, isort and flake8 check only
```

Note that CI's lint job runs `pre-commit run --all-files`, which is
broader than `./run_tests.sh lint` — it adds codespell, end-of-file-fixer,
eslint and prettier.

[AGENTS.md](AGENTS.md) holds the rules for coding agents working in this
repo, including what they may and may not do with git.

Backend app layout is in [backend/README.md](backend/README.md), frontend
layout in [frontend/README.md](frontend/README.md).

## Common errors

These are upstream's and apply to any TubeArchivist install.

### `vm.max_map_count`

Elasticsearch in Docker needs the host kernel setting `vm.max_map_count`
to be at least 262144. Temporarily:

```shell
sudo sysctl -w vm.max_map_count=262144
```

To persist it, on Ubuntu add `vm.max_map_count = 262144` to
`/etc/sysctl.conf`; on Arch create `/etc/sysctl.d/max_map_count.conf` with
the same content.

### Permissions for Elasticsearch

`Unable to access 'path.repo'` or `failed to obtain node locks` on first
start means the container cannot write to the volume. Shut it down and on
the host run:

```shell
chown 1000:0 -R /path/to/mount/point
```

### Disk usage

The Elasticsearch index turns **read only** above 95% disk usage until it
drops back under 90%, logging `disk usage exceeded flood-stage watermark`.
TubeArchivist itself misbehaves in various ways when the disk fills, so
keep ahead of it.

### `error setting rlimit`

`failed to create shim: OCI runtime create failed` usually means docker
cannot set those limits. Remove the `ulimits` key from the Elasticsearch
service in the compose file. Common under nested virtualisation, e.g.
Docker in an LXC on Proxmox.

### Port collisions

Port `8000` in use: remap it in compose with docker's host/container
distinction, e.g. `9000:8000`.

## Known limitations

* Video files need to be playable in your browser; not every codec is
  compatible with every browser.
* Every limitation of [yt-dlp](https://github.com/yt-dlp/yt-dlp) is a
  limitation here too.
* There is no flexibility in naming of the media files.

## Upstream

All of this is built on [Simon's](https://github.com/bbilly1) work.

* [tubearchivist/tubearchivist](https://github.com/tubearchivist/tubearchivist) — the upstream project
* [docs.tubearchivist.com](https://docs.tubearchivist.com/) — upstream documentation, still the reference for unchanged behaviour
* [Discord](https://www.tubearchivist.com/discord) and [r/TubeArchivist](https://www.reddit.com/r/TubeArchivist/) — upstream's community. Please don't take issues from this fork to either of them
* [CONTRIBUTING.md](CONTRIBUTING.md) — what to expect if you want to send a PR here, and a pointer to upstream's guide
* Companion projects that work against any TubeArchivist instance:
  [browser extension](https://github.com/tubearchivist/browser-extension),
  [Jellyfin plugin](https://github.com/tubearchivist/tubearchivist-jf-plugin),
  [Plex plugin](https://github.com/tubearchivist/tubearchivist-plex)
* [Screenshots](SHOWCASE.MD) — upstream's, and predating this fork's UI changes

If you find this useful, support upstream rather than this fork:
[GitHub Sponsor](https://github.com/sponsors/bbilly1),
[Paypal.me](https://paypal.me/bbilly1),
[ko-fi.com](https://ko-fi.com/bbilly1).
