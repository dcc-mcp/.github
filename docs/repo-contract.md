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
| R007 | `no-scripts-with-justfile` — no `[scripts]` entry forwards to `just` or shadows a justfile recipe | error | error | PIP-3734 |
| R008 | `agents-derived-symlink` — `CLAUDE.md` and friends are symlinks or generated | — | warning | PIP-3736 |
| R009 | `tools-no-latest` — `[tools]` pins are concrete, not `latest` | — | warning | PIP-3737 |
| R010 | `llms-txt-fresh` — `llms.txt` exists when a generator exists | — | warning | PIP-3738 |
| R011 | `no-tracked-agent-dirs` — nothing is tracked under an `agents_ide_dir` | — | error | org-agent-dirs-policy |
| R012 | `release-identity-anchored-on-tag` — release identity resolves the tag, never `github.sha` | — | warning | PIP-4497 |

R006 reports two classes of finding at different severities: a stray generated
report or a loose `*.py` at the root is an **error** (they are never legitimate),
while an entry that is simply unknown is a **warning** you can silence with
`--allow-extra` once you have decided it belongs there.

The first six rules — R001–R005 plus R007 — are mechanical: they need no product
decision, and a repository either satisfies them or it does not. The rest are
being rolled out by their owning issues, so they start out limited to `strict`
and get promoted when the rollout lands. That is the ratchet — a repository
adopts the gate before it is clean, and the warnings are the to-do list. R011 is
the exception to the "starts as a warning" pattern: it is an `error`, because by
the time it fires there is already a tracked file that has to be removed. It is
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

### Per-entry judging (R007)

R007 is judged **per `[scripts]` entry**, not per table. A repository with a
justfile may keep `[scripts]`; what it may not do is duplicate the justfile. An
entry is reported when either is true:

- **(a) forwarding** — the value runs `just <recipe>` or `vx just <recipe>`.
  Leading whitespace and triple-quoted blocks are stripped first, so a
  multi-line script whose first command is `just docs` counts.
- **(b) name collision** — the key names a recipe that exists in the justfile.
  `-` and `_` are treated as equivalent, so `test_cov` collides with `test-cov`.

Everything else is legitimate. A repository whose justfile has no build recipe
can keep `build-ue = "..."` in `[scripts]` and depend on `[env]`; a repository
whose `[scripts]` runs `uvx nox` where the justfile has no `nox` recipe is fine.

The difference matters because `vx run lint` and `just lint` are two entry
points for the same intent, and they drift — that is what R007 exists to stop.
An `[scripts]` entry the justfile does not provide has nothing to drift from, so
banning it would cost a real entry point to prevent a problem that cannot occur.

Because the rule is per entry, it is safe to make it an **error on the
`baseline` profile**: every finding is a task defined twice, and there is no
judgement call to defer. A duplicate task is duplicate by construction, which is
the same standard R001–R005 already hold. Reporting it as a `strict`-only
warning meant an adopting repository on the default `fail-on: error` saw nothing
at all, so the rule prevented recurrence only for repositories that had already
opted into `strict`.

### Opting out (R007)

Per-entry judging should already spare every legitimate entry, so an exemption
is rare. Before reaching for one, delete the duplicate — but check callers first:
removing a `[scripts]` entry also removes its `vx run <name>` command. If
anything invokes `vx run <name>`, migrate those callers to `just <name>`
first. For a name-collision entry that is not a copy of the recipe, prefer
renaming the entry over deleting it.

If a repository genuinely cannot migrate yet, understand what `skip-rules:
"R007"` does before using it: it takes the **whole rule** off the execution
plan. There is no per-entry exemption for R007 — skipping it for one unmigrated
entry also stops R007 from reporting every other duplicate in that repository,
including any added later. Treat it as disabling the rule for that repository,
not as exempting one line.

Because it is a whole-rule suspension, record it as a decision with an exit
condition rather than a setting to inherit: note what still has to be migrated
and when the skip can be removed. The nightly sweep reads the same contract, so
declare it in `contract/repositories.json` (per-repository `skip_rules`) as well
as in the caller workflow.

The forwarding commands and the interchangeable separators are configurable via
`scripts_just_forward_commands` and `scripts_recipe_name_separators` in
`contract/repo_contract.json`.

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
      error-rules: "R006,R008"
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

## Organization automation inventory (advisory)

The existing reusable `repo-contract.yml` also compares the repository under
test with [`automation_inventory.json`](../contract/automation_inventory.json).
This is a dated, representative public-source audit of `dcc-mcp`,
`try-auroraview`, and `vx-org`, **not an exhaustive list or a live org scan**.
It records source blob IDs, public PR/run evidence, and secret **names** only.
Credential availability remains `not_verified`; a secret reference is never
proof that a credential exists, has permission, or was used successfully.

The inventory schema is
[`automation_inventory.schema.json`](../contract/automation_inventory.schema.json).
Rule IDs, severities, organizations, and source-path allowlists live in
[`automation_policy.json`](../contract/automation_policy.json), in their own
`O0xx` namespace. The checker uses only the Python standard library and supports
the schema vocabulary shipped here; unsupported schema features require an
explicit implementation and tests.

| Id | Warning | Meaning |
|---|---|---|
| O001 | `automation-inventory-valid` | Schema or inventory consistency needs review, including unknown fields, bad SHAs, negative job counts, duplicate entries, and out-of-scope paths. |
| O002 | `automation-source-readable` | An audited workflow is missing, unreadable, non-regular, or symlinked. |
| O003 | `automation-source-drift` | The current checkout's Git blob ID differs from the recorded audit. Re-audit the change before refreshing the baseline. |

These warnings cannot be promoted by the existing gate's `fail-on` or
`error-rules` inputs. Invalid/unreadable inventory is explicitly reported as
`invalid`/`unavailable`, never as a clean check. The CI step is advisory even
if it cannot run; the existing repository gate retains its current behavior.

The checker reads only the registered source paths for the explicit
`owner/repository` input. It does not make API calls, read credentials, execute
workflow code, change files, or create PRs. An unregistered repository reports
`not_in_inventory`; an entry with no source files reports zero files checked.
Neither claims the repository has no workflows. New, unlisted files are not
discovered by this phase. Any byte change, including comments, causes a drift
warning; **drift is a request for review, not a semantic security finding**.
PR run evidence is historical: `action_required`, zero jobs, or a successful
manual dispatch does not establish that expected jobs ran for a PR's exact head.

```bash
# Validate the bundled audit, without reading a target checkout.
python scripts/check_automation_contract.py --validate-only --format json

# Compare one of the registered repositories with its audited workflow blobs.
python /path/to/.github/scripts/check_automation_contract.py \
  --root /path/to/checkout --repository vx-org/vx --format github
```

To refresh a baseline, review the changed public source and its exact blob ID,
update the dated inventory evidence, and run `python -m unittest discover -s
tests -v`. Never add secret values or infer credential availability. The initial
2026-10-12 audit is preserved as observed, so the new advisory step itself
intentionally causes O003 for this repository until a subsequent reviewed audit.

This phase adds no schedule or organization entrypoints and does not change
release graphs, PR writers, credentials, permissions, or the existing nightly
matrix. Existing Core PRs #2752/#2753 remain the candidates for pointer-PR reuse
and REST refresh; this checker does not duplicate their logic. Trusted-ref
adoption is a later pilot: **only after central code lands on the canonical
default branch**, pin the reusable workflow and its `ref` tooling input to the
same reviewed, full 40-hex SHA. Do not pin a PR-local commit or update all three
organizations' callers as part of this inventory change.

## Where agent skills live (R008 / `agents_ide_dirs`)

`agents_ide_dirs` is not an allowlist. A directory on that list that is present
in a repository is reported by R008 as a warning: agent directories are meant to
be generated at setup time and kept out of version control.

That makes a committed `skills/` tree under one of those directories a contract
finding rather than a supported pattern. The reason is **scope-dependent**, and
getting the scope right matters:

- **Managed agent runs** mount skills from the **organization skill registry**,
  materialised into the task's `agents_ide_dir` at startup. For these runs the
  registry is the authoritative source and a committed copy is never read.

- **Some IDE/CLI runtimes do read the repository copy.** Kimi CLI, for example,
  picks one brand group — `.kimi/skills/`, `.claude/skills/` or
  `.codex/skills/` — and scans `Project > User > Extra > Built-in`, so a
  `.kimi/skills/<id>/SKILL.md` with valid frontmatter *is* what a Kimi run in
  that repository loads.

So a committed copy is not harmless — it is worse than redundant, because it
forks from the registry and the two silently diverge. A change that lands only
in a repository looks done in review while every subsequent managed run stays
on the previous version, which is the failure this entry was written to
prevent. Land the change in the registry, and treat a repository copy as drift
whichever runtime reads it.

Export the registry copy when a byte-identical offline copy is genuinely
needed; do not commit it under an `agents_ide_dir`.

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

### R012: anchoring release identity on the tag

A release or publish workflow must not assert that the commit being published is
the commit that started the run. release-please can merge the release PR while
the run that is going to publish it is still in flight, and it then tags that
later merge commit — so a release-identity variable legitimately differs from
`github.sha`. A workflow that compares the two fails the run, and because the
next push gets `created != true` the publish job is skipped: the release ships
with no artefacts and can never self-heal. That is exactly what
dcc-mcp-reaper hit.

Two shapes are reported, both at the line that binds the run head into the
release identity:

- **a shell comparison** — `test`, `[ ]` or `[[ ]]` joining a run-head token
  (`$GITHUB_SHA`, `${{ github.sha }}`) with a release-identity variable
  (`RELEASE_SHA`, `EXPECTED_SHA`, `TAG_SHA`, `targetCommitish`, ...); a
  standalone `${{ ... }}` comparison such as
  `if: ${{ env.RELEASE_SHA != github.sha }}` counts too, and either operand may
  be a GitHub context expression (`env.X`, `steps.x.outputs.X`,
  `needs.x.outputs.X`) matched on its trailing name;
- **a YAML binding** — `EXPECTED_SHA: ${{ github.sha }}` that a later
  comparison in the same step consumes.

Everything else is legitimate, and the rule is written to say so:

- **Comments are stripped first.** Every repository that fixed this defect kept a
  comment explaining why, so a plain text search reports all of them.
- **A bare `=` is not a comparison.** `echo "source_sha=$GITHUB_SHA"` records
  provenance; only `test`, `[ ]`, `[[ ]]` and `${{ }}` expressions carrying
  `==`/`!=` are compared.
- **Only a real `test` command compares.** `test` counts at a shell command
  position (`test "$A" = "$B"`, `if test ...`, `; test ...`); the word in
  `make test NAME=...` or `echo "smoke test passed"` is an argument or prose,
  not a comparison.
- **A run head that is only recorded is not reported.** A checkout `ref:`,
  `--head-sha "$GITHUB_SHA"` and `git show "${GITHUB_SHA}:path"` name no release
  identity and assert nothing.
- **The variable has to be a release identity.** `[ "$latest_main" != "$GITHUB_SHA" ]`
  is deliberate supersede protection, and `[ "$RELEASE_TAG" != "v$RELEASE_VERSION" ]`
  compares a tag name to a version. Neither is an identity assertion.
- **A binding is scoped to its own step.** `env:` is per step, so a step that
  binds `EXPECTED_SHA` to the tag and compares it is not paired with an unrelated
  `EXPECTED_SHA: ${{ github.sha }}` three hundred lines later. Before this
  scoping existed, the gold-standard repository scored seven false positives.

The rule was validated against 100 real release/publish workflow files from 63
repositories in the org before it landed.

The files it reads and the identity names it matches are configurable via
`release_workflow_globs` and `release_identity_names` in
`contract/repo_contract.json`.

R012 recognizes shell `test`, `[` and `[[` only in command position, so
unquoted bracket text passed to `echo` or `printf` is still provenance text.
Single-quoted or escaped shell variable names are literals; double-quoted
variables still expand and remain checked. GitHub `${{ ... }}` interpolation
is checked separately because it happens before the shell, including inside
shell single quotes. This remains a bounded textual check, not a shell evaluator.

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
