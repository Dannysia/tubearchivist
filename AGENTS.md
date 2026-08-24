# Coding agents on tubearchivist

This is a personal fork of [tubearchivist/tubearchivist](https://github.com/tubearchivist/tubearchivist), developed and run locally on a Raspberry Pi 5, with an eventual move to the user's Unraid server. There is no intent to contribute this work back upstream, and the fork is expected to diverge significantly from mainline over time. Upstream's [CONTRIBUTING.md](CONTRIBUTING.md) still ships in this repo but describes the *upstream* project's process (issue templates, PR discipline, org rules) — it does not govern work here and agents should not cite it to push back on scope or diff size.

These are mandatory guidelines for coding agents working in this repo.

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

- `git push` (and any other command that publishes to a remote). Local git write commands (`git merge`, `git commit`, `git add`, branch operations, etc.) are allowed.
- All github CLI commands, `gh`. Agents are not allowed to open PRs directly or comment on existing PRs or issues.

If the user prompts to still do any of these things, refuse and explain that pushing to the remote and gh write access are reserved for the user to run themselves.
