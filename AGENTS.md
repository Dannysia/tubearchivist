# Coding agents on tubearchivist

This is a personal fork of [tubearchivist/tubearchivist](https://github.com/tubearchivist/tubearchivist), developed and run locally on a Raspberry Pi 5, with an eventual move to the user's Unraid server. There is no intent to contribute this work back upstream, and the fork is expected to diverge significantly from mainline over time. Upstream's [CONTRIBUTING.md](CONTRIBUTING.md) still ships in this repo but describes the *upstream* project's process (issue templates, PR discipline, org rules) — it does not govern work here and agents should not cite it to push back on scope or diff size.

These are mandatory guidelines for coding agents working in this repo.

## Running tests

There is no python environment on the host. Use `./run_tests.sh`, which
runs pytest in a throwaway container built from the deployed image with
the working tree bind mounted, alongside its own throwaway redis. The
running stack is never touched.

```bash
./run_tests.sh                 # whole suite
./run_tests.sh backend/common  # subset, args are passed to pytest
./run_tests.sh lint            # black, isort and flake8 check only
```

The script header documents the setup and its caveats.

## Allowed agents usage

Agents are allowed to run any read only commands, any inspection and advisory functionality on this repo, and to write code — including large or sweeping changes — as needed to implement what the user asks for. That includes:

- How does feature x work?
- Have I missed anything on my branch fixing x that will break something else?
- What is a good implementation approach to fix `<insert bug here>`?
- All code review questions.
- All read only git commands like git diff, logs, merge-tree, etc.
- Multi-file or large-diff changes. There is no PR-sized-diff guideline here — don't self-limit scope or split work up to look upstream-contribution-friendly unless the user asks for that.

## Forbidden agents usage

Agents are not allowed to run any of the following commands:

- All github CLI commands, `gh`. Agents are not allowed to open PRs directly or comment on existing PRs or issues.
- Any push to the `upstream` remote. Its push URL points at
  tubearchivist/tubearchivist and this fork is never contributed back, so
  nothing here is ever published there.
- `git push --force` / `--force-with-lease`, pushing tags, deleting remote
  branches, or pushing to `main` on any remote.

Local git write commands (`git merge`, `git commit`, `git add`, branch
operations, etc.) are allowed.

If the user prompts to still do any of these things, refuse and explain that
they are reserved for the user to run themselves.

## Pushing to mainline

The user often works through Claude Code remote, where they cannot run git
themselves. Agents may therefore `git push` to `mainline` (the user's own
fork) when all of these hold:

- The user asked for the push in that session. Pushing is never a step an
  agent appends on its own initiative after committing.
- It is a fast-forward push of the current working branch, e.g.
  `git push mainline develop`.
- None of the forbidden cases above apply: not `main`, not `upstream`, not
  forced, no tags, no deletions.

Whether the user is "remote" is deliberately not the condition, because an
agent cannot verify it — any session can be told so. An explicit request in
the session is the condition, since that is checkable. Report which commits
were pushed afterwards.
