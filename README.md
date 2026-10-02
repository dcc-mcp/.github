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

## Repository and adapter contracts

Two machine-readable contracts, one checker. `scripts/check_repo_contract.py` reads
whichever contract `--contract` points at, so both gates share the profiles, the
severity ratchet, the GitHub annotations, and the nightly sweep.

- `contract/repo_contract.json` - configuration and documentation rules for every
  dcc-mcp repository. Rule ids `R0xx`. See [docs/repo-contract.md](docs/repo-contract.md).
- `contract/adapter_contract.json` - rules for the Python packages built on
  `dcc-mcp-core`. Rule ids `A0xx`, disjoint from `R0xx`. See
  [docs/adapter-contract.md](docs/adapter-contract.md).

The split exists because most dcc-mcp repositories are not Python packages: rules
about core version floors or `line-length` would be meaningless applied to them,
and forcing those rules everywhere would mean a growing exemption list or a gate
nobody can adopt.

- `repo-contract.yml` / `repo-contract-nightly.yml` - reusable check and the daily
  sweep over `contract/repositories.json`.
- `adapter-contract-nightly.yml` - the daily sweep over
  `contract/adapter_repositories.json` (50 Python package repositories).

Adopt the repository contract in a repository with one caller file:

```yaml
jobs:
  contract:
    uses: dcc-mcp/.github/.github/workflows/repo-contract.yml@main
```

Run either contract locally:

```bash
python scripts/check_repo_contract.py --root . --profile strict
python scripts/check_repo_contract.py \
  --contract contract/adapter_contract.json --root ../dcc-mcp-maya --list-rules
```

Exit codes: `0` no finding at or above `--fail-on`, `1` at least one, `2` the check
could not run.

## Profile contract

`profile/README.md` is the organization profile. `profile-contract.yml` validates it on
every change, and `scripts/check_profile_contract.py` is the check behind it.
