# Repository contract

A mechanical gate for the configuration and documentation contract agreed in
PIP-3741. It exists because the previous seven cleanups were one-off edits with
nothing to stop the drift coming back.

The rules and their severities are defined once, in
[`contract/repo_contract.json`](../contract/repo_contract.json). The CI gate
([`scripts/check_repo_contract.py`](../scripts/check_repo_contract.py)) and the
`vx-repo-contract` skill both read that file, so a criterion is never written
down twice.

This contract covers every repository in the org. Repositories that publish a
`dcc-mcp-*` Python package are additionally checked against
[`contract/adapter_contract.json`](../contract/adapter_contract.json), described
in [adapter-contract.md](adapter-contract.md).

## Rules

| Id | Rule | `baseline` | `strict` | Decided by |
|---|---|---|---|---|
| R001 | `no-root-artifacts` — no build or test artifacts at the root | error | error | PIP-3735 |
| R002 | `justfile-lowercase` — `justfile`, never `Justfile` | error | error | PIP-3735 |
| R003 | `agents-md-exists` — `AGENTS.md` is present | error | error | PIP-3736 |
| R004 | `vx-toml-parses` — `vx.toml` parses into known tables | error | error | PIP-3737 |
| R005 | `tools-version-format` — `[tools]` pins are `stable`, `latest`, `X[.Y[.Z]]`, or a declared delegation sentinel | error | error | PIP-3737 |
| R006 | `root-allowlist` — every top-level entry is allowlisted | — | warning | PIP-3735 |
| R007 | `no-scripts-with-justfile` — no `vx.toml [scripts]` when a justfile exists | — | warning | PIP-3734 |
| R008 | `agents-derived-symlink` — `CLAUDE.md` and friends are symlinks or generated | — | warning | PIP-3736 |
| R009 | `tools-no-latest` — `[tools]` pins are concrete, not `latest` | — | warning | PIP-3737 |
| R010 | `llms-txt-fresh` — `llms.txt` exists when a generator exists | — | warning | PIP-3738 |
| R011 | `no-tracked-agent-dirs` — nothing is tracked under an `agents_ide_dir` | — | error | org-agent-dirs-policy |

R006 reports two classes of finding at different severities: a stray generated
report or a loose `*.py` at the root is an **error** (they are never legitimate),
while an entry that is simply unknown is a **warning** you can silence with
`--allow-extra` once you have decided it belongs there.

The first five rules are mechanical: they need no product decision, and a
repository either satisfies them or it does not. The last six are being rolled
out by their owning issues, so they start out limited to `strict` and get
promoted when the rollout lands. That is the ratchet — a repository adopts the
gate before it is clean, and the warnings are the to-do list. R011 is the
exception to the "starts as a warning" pattern: it is an `error`, because by the
time it fires there is already a tracked file that has to be removed. It is
scoped to `strict` only while the handful of repositories with a pre-existing
committed agent tree are cleaned up.

### Delegation sentinels (R005)

Some tools are deliberately owned by another manager. A repository that pins its
Rust toolchain in `rust-toolchain.toml` wants rustup to own it, and records that
in `vx.toml` as an explicit opt-out:

```toml
[tools]
rust = "rustup-managed"
```

`rustup-managed` is an **ownership declaration, not a version**, so it does not
match `tools_version_pattern`. R005 accepts it anyway, because vx *can* resolve
that pin — it resolves to "ask rustup" — and a sentinel is exactly as
reproducible as the toolchain file it points at. The point of R005 is to reject
pins vx cannot act on: bare channel names, ranges, and URLs.

The exemption is scoped per tool, via `tools_delegation_sentinels` in
`contract/repo_contract.json`. `rust` may declare `rustup-managed`;
`python = "rustup-managed"` is still an error. When another proxy-managed runtime
needs a sentinel, add it there. Do not widen `tools_version_pattern` instead —
that would let every tool claim every sentinel.

## Adopting the gate

Add one workflow file to the repository:

```yaml
name: Repo contract

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  contract:
    uses: dcc-mcp/.github/.github/workflows/repo-contract.yml@main
```

That runs the `baseline` profile. To ratchet up, pass inputs:

```yaml
jobs:
  contract:
    uses: dcc-mcp/.github/.github/workflows/repo-contract.yml@main
    with:
      profile: strict
      error-rules: "R006,R007,R008"
      fail-on: warning
```

Available inputs: `ref`, `profile` (`baseline` | `strict` | `all`), `rules`,
`skip-rules`, `error-rules`, `allow-extra`, `fail-on` (`error` | `warning` |
`none`).

Repositories can also be swept without adding any file: list them in
[`contract/repositories.json`](../contract/repositories.json) and the
`repo-contract-nightly` workflow checks them once a day, the same way
`release-integrity-nightly` does. Prefer the nightly manifest for repositories
you are surveying, and the caller workflow for repositories you own.

## Running it locally

```bash
# In any repository
python /path/to/dcc-mcp/.github/scripts/check_repo_contract.py --root . --profile strict

# Human-readable, exit code only, JSON for tooling
... --format text
... --format json

# What does the contract actually say?
... --emit-contract
... --list-rules --profile strict
```

Findings are emitted as GitHub annotations
(`::error file=vx.toml,title=Repo contract R005::...`) so they appear on the file
in the PR diff.

## Where agent skills live (R008 / `agents_ide_dirs`)

`agents_ide_dirs` is not an allowlist. A directory on that list that is present
in a repository is reported by R008 as a warning: agent directories are meant to
be generated at setup time and kept out of version control.

That makes a committed `skills/` tree under one of those directories a contract
finding rather than a supported pattern. The reason is **scope-dependent**, and
getting the scope right matters:

- **Monica-managed runs** mount skills from the **workspace skill registry**,
  materialised into the task's `agents_ide_dir` at startup. For these runs the
  registry is the authoritative source and a committed copy is never read.

- **Some IDE/CLI runtimes do read the repository copy.** Kimi CLI, for example,
  picks one brand group — `.kimi/skills/`, `.claude/skills/` or
  `.codex/skills/` — and scans `Project > User > Extra > Built-in`, so a
  `.kimi/skills/<id>/SKILL.md` with valid frontmatter *is* what a Kimi run in
  that repository loads.

So a committed copy is not harmless — it is worse than redundant, because it
forks from the registry and the two silently diverge. A change that lands only
in a repository looks done in review while leaving every subsequent Monica run
on the previous version, which is the failure this entry was written to prevent
(PIP-4292). Land the change in the registry, and treat a repository copy as
drift whichever runtime reads it.

```bash
monica skill list --output json                       # canonical source of truth
monica skill get <skill-id> --with-content            # read the mounted bytes
monica skill files upsert <skill-id> --path scripts/x.py --content-file x.py
monica skill update <skill-id> --content-file SKILL.md
```

Export the registry copy with `monica skill export <skill-id> --dir <dir>`
when a byte-identical offline copy is genuinely needed; do not commit it under
an `agents_ide_dir`.

### R011: catching a committed copy

R008 warns that an agent directory exists. R011 goes one step further and
reports **each tracked file** under one, at `error` severity, with the exact
remediation:

```
.kimi/skills/code-review/SKILL.md is tracked under the agent/IDE directory
`.kimi/`; add `/.kimi/` to .gitignore and untrack it, or move the asset to a
committed path outside the agent directories
```

The distinction matters. A single warning naming a directory is easy to scroll
past, and a whole skill tree is twenty files — which is why a committed tree
survived review and CI in the first place. Listing the files also makes the
migration reviewable: every path in the output is a decision about where that
content should live.

R008 stands down on a directory once R011 has reported files under it, so a
committed tree produces one set of findings rather than two.

The check asks `git ls-files` which files are version-controlled, so output
sitting inside an already-ignored agent directory is not reported. Outside a git
working tree it falls back to listing the directory.

## Changing a rule

Edit `contract/repo_contract.json` — not the script. The script only implements
the mechanics (parse TOML, list the root, read a symlink) and reads every
threshold, allowlist, and severity from the contract. Adding a rule means adding
a `rules` entry plus a handler in `RULES`; `tests/test_repo_contract.py` asserts
the two stay in sync.

## Sharing the definition with vx

`check_repo_contract.py --emit-contract` prints the whole contract as JSON. The
`vx-repo-contract` skill should vendor that output (or fetch
`contract/repo_contract.json` from `dcc-mcp/.github@main`) rather than keeping its
own copy of the allowlist, so `vx ai check` and CI cannot disagree.
