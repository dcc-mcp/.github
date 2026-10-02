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
| A010 | `no-deprecated-schema-alias` — adapter code does not reference the deprecated `INSTALL_SOP_SCHEMA_VERSION` alias | **error** | error | PIP-4106 |
| A011 | `report-schema-version-source` — the report `schema_version` comes from the schema `const`, not from a literal or the artifact revision | — | warning | PIP-4106 |
| A012 | `core-floor-policy` — the declared `dcc-mcp-core` floor is at or above the organisation baseline | — | warning | PIP-4106 |
| A013 | `doctor-module-present` — an adapter with install capability ships a `doctor` self-check module | — | warning | PIP-4106 |
| A014 | `report-validates-against-schema` — a real report is validated with `validate_install_sop_report()` in tests or CI | — | warning | PIP-4106 |

A001 is the **applicability gate**, not a business rule. It answers one question
the other rules cannot answer for themselves: *is this repository actually an
adapter package?* Everything else in this contract assumes the answer is yes, so
A001 has to be able to say no.

A010 is the only rule besides A001 that sits in `baseline`, and the only one
that fails the build: it is decided from source text alone, needs no core at
runtime, and has no migration cost, so there is no reason to ratchet it. A011
to A014 report the gap and start as warnings.

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

## How the Install SOP family decides

`dcc-mcp-core` `0.20.40` split one name into two, and the family exists to keep
adapters from putting the wrong one on the wire:

- `INSTALL_SOP_SCHEMA_REVISION` — the revision of the published schema
  *artifact* (`adapter-install-sop-vN.schema.json`), currently `2`.
- `install_sop_report_schema_version()` — the value a report document's
  `schema_version` field must carry. It reads
  `properties.schema_version.const` from the schema and is `1`; publishing
  `-v(N+1)` adds optional members and never moves it.

The old `INSTALL_SOP_SCHEMA_VERSION` is a deprecated alias that `__getattr__`
still serves with a `DeprecationWarning`, which is why **A010** can be an error
immediately: whether adapter source references it is decidable from the text.
The one exemption is a file that defines or serves the alias — that is core
keeping old adapters working, and flagging it would penalise the only
repository that is supposed to have it.

**A011** reads an Install SOP report envelope with `ast`, not with a regex, and
only considers dicts that carry an Install SOP marker key (`steps`,
`next_steps`, `receipt_path`). Adapters ship other schemas that also have a
`schema_version` — a deck IR, a patch format — and without that scoping the
rule reports documents that have nothing to do with the Install SOP. Two
sources are rejected: the artifact revision, which is the defect that shipped in
PIP-3990, and a hardcoded literal.

A hardcoded literal is **accepted when a test pins it to the schema `const`**.
An adapter that writes `SCHEMA_VERSION = 1` and asserts
`SCHEMA_VERSION == install_sop_report_schema_version()` has already closed the
drift this rule is for, and a gate that reports a defended adapter is a gate
people learn to ignore. The known trade-off is that a guard is matched by name
across files, so a second, unrelated constant sharing a guarded name is also
excused. That is the deliberate direction to err in for a warning.

**A012** compares the declared `dcc-mcp-core` floor against
`core_floor_baseline` (`0.20.36`), which is the highest floor any adapter
declares today, so the target is reachable rather than aspirational.
`core_floor_target` (`0.20.40`) is where the new Install SOP API becomes
unconditionally available; meeting the baseline but not the target is a
`notice`, which is reported but can never fail a run. The floor is read through
the same `parse_pyproject` reader and the same `dependency_key_patterns` that
A001 uses, so the two rules cannot disagree about what a package declares.

**A013** and **A014** are skipped for an adapter with no Install SOP surface at
all. Roughly 42 of the 50 adapters neither reference the Install SOP contract
nor ship an install module, and reporting them for a gap they do not have would
bury the real findings.

## The nightly sweep

[`.github/workflows/adapter-contract-nightly.yml`](../.github/workflows/adapter-contract-nightly.yml)
mirrors `repo-contract-nightly.yml`: one job builds the matrix from
`contract/adapter_repositories.json` with `--emit-matrix`, one job per
repository checks it out and runs the gate. Adopting the adapter contract needs
**no workflow file in the adapter repository** — that is the point, because the
gap this contract exists to close is that 50 repositories each drifted in their
own direction.

The manifest defaults are `profile: baseline`, `fail_on: error`. In `baseline`
the sweep runs A001 and A010, so a repository that still references the
deprecated `INSTALL_SOP_SCHEMA_VERSION` alias fails the sweep while an
unregistered or non-Python repository only draws an A001 warning. Running the
sweep with `profile: strict` adds A011 to A014, whose warnings are the gap list;
the ratchet is what turns them red.

## Ratchet plan

The warnings are the to-do list. Promoting a rule is a two-step move, never a
big-bang edit across 50 repositories:

1. **Visible.** The rule lands as a `warning` in `strict` (or in `baseline`, as
   A001 does) and the nightly reports the gap per repository.
2. **Binding.** Once the owning issue has driven the count down, the rule moves
   to `error`, or a repository that is clean promotes it for itself with
   `error_rules` in its manifest entry.

The Install SOP family (A010 to A014) is the current ratchet target. Only A010
is binding today; the other four start as warnings because the `dcc-mcp-core`
floor declarations across the fleet are as low as `>=0.18.2` while the
replacement API only exists from `0.20.40`. Every threshold the family uses —
`core_floor_baseline`, `core_floor_target`, the symbol names, the globs — is a
contract value, so moving a threshold is an edit to the JSON and not a code
change.

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
