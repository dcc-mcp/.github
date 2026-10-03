# .github

Organization-level defaults and shared automation for the [dcc-mcp](https://github.com/dcc-mcp) organization.

## Release integrity

A GitHub release and the matching PyPI upload are produced by two separate steps, so a
release can exist on GitHub while the package never reaches PyPI. Nothing in the current
gates compares the two, which lets a broken publish stay green indefinitely.

`.github/workflows/release-integrity.yml` closes that gap: for every repository/package
pair it compares the newest GitHub release tag (leading `v` stripped) against
`https://pypi.org/pypi/<package>/json` and **fails on a mismatch**.

- `release-integrity.yml` - the reusable check (`workflow_call` + `workflow_dispatch`).
- `release-integrity-nightly.yml` - runs the check daily over the built-in manifest: every
  dcc-mcp repository that publishes to a project that exists on PyPI (36 repositories /
  38 packages, including `dcc-mcp-core`, which also publishes `dcc-mcp-server` and
  `dcc-mcp-core-semantic`). The manifest is written out twice, as the `repositories`
  default of **both** the `workflow_call` and the `workflow_dispatch` inputs in
  `release-integrity.yml`; update **both** copies and keep them identical, because the
  nightly schedule only reads the `workflow_call` one.
- `scripts/check_release_integrity.py` - the comparison itself; it can be run locally.

A mismatch is tolerated (reported as a warning instead of a failure) when the release was
published less than `grace_minutes` ago, because a PyPI upload lands a few minutes after
the GitHub release, or when PyPI is already ahead of the newest stable release, which is
normal for a pre-release upload. Everything else fails.

### Running it locally

```bash
python scripts/check_release_integrity.py \
  --repository dcc-mcp/dcc-mcp-maya --package dcc-mcp-maya

python scripts/check_release_integrity.py --manifest '[
  {"repository": "dcc-mcp/dcc-mcp-core",
   "packages": ["dcc-mcp-core", "dcc-mcp-server", "dcc-mcp-core-semantic"]}
]'
```

Exit codes: `0` consistent, `1` inconsistent, `2` the check could not run.

### Using it from another repository

```yaml
jobs:
  release-integrity:
    uses: dcc-mcp/.github/.github/workflows/release-integrity.yml@main
    with:
      repositories: '[{"repository":"dcc-mcp/dcc-mcp-maya","packages":["dcc-mcp-maya"]}]'
      grace_minutes: "30"
```

Omit `repositories` to use the built-in manifest of every PyPI-publishing dcc-mcp
repository. Set `strict: true` to fail on tolerated mismatches as well.

`tests/test_release_integrity_manifest.py` asserts the two copies stay identical, so a
half-applied manifest edit fails the Profile contract workflow instead of silently
leaving the nightly gate on an outdated list.

## Release CI gate

Release integrity answers "did the release reach PyPI?". This gate answers the question
that comes *before* the merge: **has CI actually run for this release pull request?**

Those are not the same question, and the second one is harder than it looks. A pull
request whose CI is parked in GitHub's manual approval queue has **no check runs at
all**: `gh pr checks` prints nothing, `statusCheckRollup` is empty (or one all-`null`
entry), and `mergeable` is `MERGEABLE`. Nothing tells you CI is waiting — it looks
exactly like a pull request that has no CI. A release window that trusts `mergeable`
then publishes a version no CI ever validated, which is how `dcc-mcp-premiere` v0.6.2
shipped.

The runs behind this are all authored by `github-actions[bot]`: release-please opens
the pull request with `secrets.GITHUB_TOKEN`, GitHub does not treat that bot as a
trusted collaborator, so its `pull_request` runs go to the approval queue. The same
branch pushed from an account with write access runs immediately — which is why some
repositories never see this. `dcc-mcp-houdini` proves the fix: its `release.yml` passes
`secrets.PERSONAL_ACCESS_TOKEN`, so its release pull requests are authored by a real
collaborator and their CI runs at once.

A second silent shape is worse, because it inverts the signal. Merging a pull request
that still has a run in the approval queue makes GitHub flip that run to
`conclusion=failure` — **while it still has zero jobs**. So "CI is red" on a release
pull request frequently means "an approval request was invalidated by the merge", not
"a test failed". Treating it as red is as wrong as treating it as green, and it sends
the next reader looking for a test failure that does not exist.

`scripts/check_release_ci_gate.py` therefore never trusts `conclusion`. It counts
**jobs**, and returns one of four verdicts:

| Verdict | Meaning | Mergeable |
|---|---|---|
| `green` | every run completed successfully and at least one job ran | yes |
| `red` | a run executed jobs and did not succeed | no |
| `pending` | a run has not finished yet | no |
| `no_evidence` | no run produced a single job | no |

`no_evidence` carries a reason: `awaiting_approval` (a run sits in the approval queue),
`approval_invalidated` (a zero-job failure — a workflow that never ran, usually an
approval overtaken by the merge), or `no_runs` (nothing was ever triggered). Partial
evidence is not green either: if CI passed but E2E produced a run that executed zero
jobs, the verdict is `no_evidence`, because merging ships a version only part of the
suite saw.

Be precise about the limit of that rule, because the difference matters to anyone
writing automation against this gate. What is caught is a suite that **produced a run
which executed no jobs**. A suite that was **never triggered at all** is invisible
here — if a pull request has only a CI run and no E2E run object exists, the verdict is
`green`. Telling those two apart needs a per-repository list of which suites are
expected, which this check does not have. Do not read `green` as "every suite in the
repository passed"; read it as "every run that exists produced jobs and succeeded".

### Sweeping the open release pull requests

This is what a release window runs before merging anything:

```bash
python scripts/check_release_ci_gate.py --open-prs
python scripts/check_release_ci_gate.py --open-prs --repositories dcc-mcp/dcc-mcp-maya,dcc-mcp/dcc-mcp-nuke
```

### Deciding one pull request

```bash
python scripts/check_release_ci_gate.py --pr dcc-mcp/dcc-mcp-premiere#19
```

The verdict is always against the **exact head commit**, never the merge commit. When
the pull request is already merged the report also shows the push runs of the merge
commit, as labelled context: it tells you whether an already-published release has to
be rolled back, and it is never a substitute for the head-commit verdict.

### Listing the parked runs

```bash
python scripts/check_release_ci_gate.py --org dcc-mcp --format json
```

Add `--approve` to approve the parked runs the sweep finds. It is off by default:
approving only lets an already-queued run execute, but it is a live action and should
be deliberate.

Exit codes: `0` no finding, `1` at least one finding at or above `--fail-on`
(default `no_evidence`), `2` the check could not be performed.

### Running it from a repository

- `release-ci-gate.yml` - the reusable check (`workflow_call` + `workflow_dispatch`).
- `release-ci-gate-nightly.yml` - sweeps every open release pull request in the
  organization once a day and **fails** on any `no_evidence` verdict, so a parked run
  stops being silent.

```yaml
jobs:
  release-ci-gate:
    uses: dcc-mcp/.github/.github/workflows/release-ci-gate.yml@main
```

### Removing the cause

The gate stops the merge; it does not stop the queue. To stop runs from parking in the
first place, give release-please a token that belongs to an account with write access
instead of `secrets.GITHUB_TOKEN`:

```yaml
- uses: googleapis/release-please-action@v5
  with:
    token: ${{ secrets.PERSONAL_ACCESS_TOKEN }}
```

That is the single change that removes the failure mode, and it is per-repository:
`dcc-mcp-houdini` already works this way. Until every repository does, the gate is what
keeps a parked run from being read as "no CI, therefore fine".

## Repository contract

Two machine-readable contracts share one checker, `scripts/check_repo_contract.py`, which
loads whichever one you point `--contract` at. The rules and their severities live in the
JSON under `contract/`, never in the script.

| Contract | Ids | Applies to | Docs |
|---|---|---|---|
| `contract/repo_contract.json` | `R0xx` | every repository | [docs/repo-contract.md](docs/repo-contract.md) |
| `contract/adapter_contract.json` | `A0xx` | the 50 repositories shipping a Python package | [docs/adapter-contract.md](docs/adapter-contract.md) |

### Adapter contract

The 50 dcc-mcp repositories that ship a Python package had converged on nothing: five
spellings of the Install SOP report's `schema_version` field, three `line-length` values,
a 54-patch spread of `dcc-mcp-core` floors, and 6 of 50 with a pre-commit config. The
adapter contract turns that into a gate.

- `adapter-contract-nightly.yml` - sweeps every repository in
  `contract/adapter_repositories.json` once a day, with `--profile strict --fail-on error`,
  so the two baseline rules block regressions and the four convergence rules are emitted as
  the stock-take list.
- `contract/adapter_contract.json` - the rules. `A001` (no reference to Core's deprecated
  `INSTALL_SOP_SCHEMA_VERSION`) and `A003` (a declared Core dependency pins a lower bound)
  are errors in `baseline`; `A002`, `A004`, `A005` and `A006` are warnings in `strict`.

`A001` is an error from day one because every existing reference already sits behind a
`try/except ImportError` fallback, so deleting it needs no Core floor bump. Which fix applies
depends on what the value means, and the two cases need opposite edits: where the value is the
schema *artifact revision* only the name is deprecated, so rename it to
`INSTALL_SOP_SCHEMA_REVISION`; where the value feeds a report's `schema_version`, or is a
vestigial import, delete the reference and read the field from
`install_sop_report_schema_version()`. What is never allowed is a rename that only makes the
gate go green: where the value reaches a report's `schema_version`, that keeps the artifact
revision flowing into a field the schema pins at `1`, which is the defect
PIP-4047/4048/4049/4050/4051 fixed one repository at a time. The full rule, with the counts per
case, is in [docs/adapter-contract.md](docs/adapter-contract.md).

Run it locally against any adapter:

```bash
python scripts/check_repo_contract.py \
  --root /path/to/dcc-mcp-maya \
  --contract contract/adapter_contract.json \
  --profile strict --format text
```

## Profile contract

`profile/README.md` is the organization profile. `profile-contract.yml` validates it on
every change, and `scripts/check_profile_contract.py` is the check behind it.
