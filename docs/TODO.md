# Known gaps, not scheduled

Things worth doing that are deliberately not being done yet. Not a
roadmap and not a promise — a place to write down what is already known
so it does not have to be rediscovered.

## No frontend tests

Every automated test in this repo is backend. The UI has grown a lot —
the import modal with its two channel modes and debounced typeahead, the
video filters, channel list sorting, the stats components — and every
regression in any of it is currently caught by hand in a browser, or not
at all.

Nothing is set up: no vitest, no testing-library, no jsdom. That is the
real cost, since the first test is most of the work and the rest are
cheap after it.

Worth covering first, roughly in order of how quietly they would break:

- `ImportMetadataModal` — mode switching clears both channel fields, the
  debounce fires once per pause, the completeness check gates the submit
- `Filterbar` — the downscale/codec filters write the right user config
  keys, and the codec select hides itself when nothing is downscaled
- `ChannelStats` / `DownscaleStats` — panels hide on zero, percentages
  render, `ALL_ENCODER_LABELS` falls back to the raw encoder string
- `Footer` — the build id renders only when present, dirty is visible

## Thin backend coverage

Two apps are noticeably behind the rest:

- `user` — 2 source files, 0 tests, and it holds auth plus the user
  config that several features now key off
- `download` — 8 source files, 2 tests, and it is the core queue

## No signal when a deploy is behind

CI builds and pushes `:mainline` on every push to `develop`, but nothing
pulls it — the Unraid update is manual and deliberately stays that way.
The footer now shows which build is running, so the drift is visible,
but only if you go and look. That is how the import stub bug stayed
broken in prod after it was fixed and verified locally.

A notice in the footer would close it, reusing the shape of the existing
upstream update check: a scheduled task compares the running
`TA_BUILD_SHA` against the newest build available and sets a redis key,
the footer renders it. The comparison target could be the latest commit
on `develop` via the GitHub API, or the `sha-*` tag list on the GHCR
package. Auto deploying is explicitly not wanted.

## History is recorded but never shown

`ta_history` records every field a refresh changes, and nothing surfaces
it. The index, the writer and its tests exist; there is no reader, no
API and no UI. See [metadata-history](metadata-history/README.md).
