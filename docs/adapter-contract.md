# Adapter contract

A mechanical gate for the Python adapter packages in the `dcc-mcp` organisation:
50 repositories that all ship a `pyproject.toml`, all depend on `dcc-mcp-core`,
and have been drifting apart in how they use the shared API. The rules are
defined once, in
[`contract/adapter_contract.json`](../contract/adapter_contract.json), and read
by both [`scripts/check_repo_contract.py`](../scripts/check_repo_contract.py)
and the `vx-repo-contract` skill, so a criterion is never written down twice.

This is a **second contract, not a second system**. `--contract` points the
existing checker at a different rule file; the CI gate, the GitHub annotations,
the `--emit-matrix` sweep and the skill all work exactly as they do for
[`docs/repo-contract.md`](repo-contract.md).

## Why a separate file

The repository contract (`contract/repo_contract.json`) applies to *every*
repository the organisation sweeps, including non-Python ones such as
`loonghao/vx` and `loonghao/cua`. Rules like "do not reference the deprecated
`INSTALL_SOP_SCHEMA_VERSION` alias" are meaningless there, and adding them to
the shared contract would force Rust and TypeScript repositories to satisfy
Python adapter rules.

So the adapter rules live in their own file with their own id namespace:

| Contract | Ids | Applies to |
|---|---|---|
| `contract/repo_contract.json` | `R0xx` | every repository in `contract/repositories.json` |
| `contract/adapter_contract.json` | `A0xx` | the Python adapter packages in `contract/adapter_repositories.json` |

The namespaces are disjoint and the checker resolves ids against the selected
contract only, so `--contract contract/adapter_contract.json --rule R001` is an
error rather than a silently mis-selected rule.

## Rules

| Id | Rule | `baseline` | `strict` | Decided by |
|---|---|---|---|---|
| A001 | `adapter-python-package` — a registered adapter ships a `pyproject.toml` that declares a `dcc-mcp-core` dependency | warning | warning | PIP-4105 |

A001 is the **applicability gate**, not a business rule. It answers one question
the other rules cannot answer for themselves: *is this repository actually an
adapter package?* Everything else in this contract assumes the answer is yes, so
A001 has to be able to say no.

## How A001 decides

It reads `pyproject.toml`, collects every dependency array whose key matches a
`dependency_key_patterns` entry, strips PEP 508 specifiers, extras and
environment markers, and normalises the names the way PEP 503 does.

```toml
[project]
name = "dcc-mcp-maya"
dependencies = [
    "dcc-mcp-core[server]>=0.20.40",   # matches: extra and specifier stripped
]

[dependency-groups]
dev = ["dcc_mcp_core"]                 # matches: underscores normalise to dashes
```

A repository passes when any searched array declares a `core_distribution_names`
entry. It also passes when its own distribution name is in
`self_distributions` — `dcc-mcp-core` is what adapters depend on, so it cannot
depend on itself. Everything else reports a warning naming the fix: declare the
dependency, or drop the repository from the nightly manifest.

The searched keys, the core names and the exempt distributions all live in
`contract/adapter_contract.json`. Nothing about the predicate is hardcoded in
the checker.

A manifest the reader cannot model is reported as a finding rather than
crashing: one exotic `pyproject.toml` must not take down a 50-repository sweep.

## The nightly sweep

[`.github/workflows/adapter-contract-nightly.yml`](../.github/workflows/adapter-contract-nightly.yml)
mirrors `repo-contract-nightly.yml`: one job builds the matrix from
`contract/adapter_repositories.json` with `--emit-matrix`, one job per
repository checks it out and runs the gate. Adopting the adapter contract needs
**no workflow file in the adapter repository** — that is the point, because the
gap this contract exists to close is that 50 repositories each drifted in their
own direction.

The manifest defaults are `profile: baseline`, `fail_on: error`. With only A001
in the contract that means the sweep is green and the warnings are the gap list;
the ratchet is what turns them red.

## Ratchet plan

The warnings are the to-do list. Promoting a rule is a two-step move, never a
big-bang edit across 50 repositories:

1. **Visible.** The rule lands as a `warning` in `strict` (or in `baseline`, as
   A001 does) and the nightly reports the gap per repository.
2. **Binding.** Once the owning issue has driven the count down, the rule moves
   to `error`, or a repository that is clean promotes it for itself with
   `error_rules` in its manifest entry.

PIP-4106 adds the Install SOP interface rules on top of this contract. A010
(`no-deprecated-schema-alias`) is planned to land directly at `error` because it
is a purely static check with no migration cost; the rest start at `warning`
because the `dcc-mcp-core` floor declarations across the fleet are as low as
`>=0.18.2` while the replacement API only exists from `0.20.40`.

## Running it locally

```bash
# In any adapter repository
python /path/to/dcc-mcp/.github/scripts/check_repo_contract.py \
  --root . --contract contract/adapter_contract.json --profile baseline

# Does --contract reach the rules?
... --contract contract/adapter_contract.json --list-rules --profile baseline

# What does the contract actually say?
... --contract contract/adapter_contract.json --emit-contract
```

Findings are emitted as GitHub annotations
(`::warning file=pyproject.toml,title=Repo contract A001::...`) so they appear on
the file in the PR diff.

## Changing a rule

Edit `contract/adapter_contract.json` — not the script. Adding a rule means
adding a `rules` entry plus a handler in `RULES`;
`tests/test_repo_contract.py` asserts the two stay in sync, that every handler
is claimed by a contract, and that the two contracts keep disjoint id
namespaces.

If a repository turns out not to belong in the sweep, remove it from
`contract/adapter_repositories.json` rather than widening a rule. A001 exists so
that this decision is made explicitly instead of being buried in an exemption
list.
