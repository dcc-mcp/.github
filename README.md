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
  `dcc-mcp-core-semantic`). The manifest is the `repositories` default in
  `release-integrity.yml` - edit it there and both entry points stay in sync.
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

## Profile contract

`profile/README.md` is the organization profile. `profile-contract.yml` validates it on
every change, and `scripts/check_profile_contract.py` is the check behind it.
