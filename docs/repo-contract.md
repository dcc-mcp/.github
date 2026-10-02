# Repository contract

A mechanical gate for the configuration and documentation contract agreed in
PIP-3741. It exists because the previous seven cleanups were one-off edits with
nothing to stop the drift coming back.

The rules and their severities are defined once, in
[`contract/repo_contract.json`](../contract/repo_contract.json). The CI gate
([`scripts/check_repo_contract.py`](../scripts/check_repo_contract.py)) and the
`vx-repo-contract` skill both read that file, so a criterion is never written
down twice.

`R0xx` is not the only rule namespace. `--contract` points the same checker at a
different rule file, and [`docs/adapter-contract.md`](adapter-contract.md)
describes `contract/adapter_contract.json`: the `A0xx` rules that apply only to
the Python adapter packages. The two are deliberately separate so that a
non-Python repository never has to satisfy an adapter rule.

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

R006 reports two classes of finding at different severities: a stray generated
report or a loose `*.py` at the root is an **error** (they are never legitimate),
while an entry that is simply unknown is a **warning** you can silence with
`--allow-extra` once you have decided it belongs there.

The first five rules are mechanical: they need no product decision, and a
repository either satisfies them or it does not. The last five are being rolled
out by their owning issues, so they start as warnings and get promoted when the
rollout lands. That is the ratchet — a repository adopts the gate before it is
clean, and the warnings are the to-do list.

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

# The adapter rules instead of these ones (see docs/adapter-contract.md)
... --contract /path/to/dcc-mcp/.github/contract/adapter_contract.json --root .
```

Findings are emitted as GitHub annotations
(`::error file=vx.toml,title=Repo contract R005::...`) so they appear on the file
in the PR diff.

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
