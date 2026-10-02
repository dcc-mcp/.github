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
`try/except ImportError` fallback, so deleting it needs no Core floor bump - but the fix is
deletion, never a rename. Renaming would keep the artifact revision flowing into the report
field, which is the defect PIP-4047/4048/4049/4050/4051 fixed one repository at a time.

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
