# Adapter contract

A mechanical gate for the Python packages that build on `dcc-mcp-core`. It exists
because the same thing is written N different ways across the organisation's
adapter repositories, and a convention that lives only in documentation drifts
back the moment it is applied.

The rules and their severities are defined once, in
[`contract/adapter_contract.json`](../contract/adapter_contract.json). The CI gate
and the nightly sweep both read that file, so a criterion is never written down
twice.

## Why a second contract instead of more R-rules

The repository contract already gates every `dcc-mcp` repository, but most of those
repositories are not Python packages. Rules about `dcc-mcp-core` version floors or
`line-length` would be meaningless applied to `loonghao/vx`, and forcing them there
would mean either a growing exemption list or a gate nobody can adopt.

So the adapter contract is a **second contract file read by the same checker**:

```bash
python scripts/check_repo_contract.py --contract contract/adapter_contract.json --root .
```

That reuses the profiles, the severity ratchet, the GitHub annotations, the matrix
builder, and the nightly sweep without redefining any of them. The only thing that
separates the two gates is which JSON file is loaded. Rules use the `A0xx`
namespace so the two contracts can never collide, and
`tests/test_repo_contract.py` asserts the namespaces stay disjoint.

## Scope: which repositories this applies to

A repository is in scope when it ships a `pyproject.toml` that declares a
`dcc-mcp-core` dependency. Measured 2026-10-02 across all 94 organisation
repositories:

| Category | Count | Disposition |
|---|---|---|
| `dcc-mcp-*` with a `pyproject.toml` | 50 | Registered here |
| — of those, declaring `dcc-mcp-core` | 46 | In scope |
| `dcc-mcp-*` without a `pyproject.toml` | 8 | Out of scope; stay on the repository contract |

The eight without a `pyproject.toml` are `dcc-mcp-excel`, `word`, `outlook`,
`office`, `agent-plugins`, `maya-advancedskeleton`, `maya-mgear`, and `inkscape`.
Their nature has not been confirmed repo by repo; until it is, they stay out of
this contract rather than being registered and permanently reported as
out-of-scope.

## Rules

| Id | Rule | `baseline` | `strict` | Decided by |
|---|---|---|---|---|
| A001 | `adapter-python-package` — a `pyproject.toml` declaring `dcc-mcp-core` | notice | notice | PIP-4105 |

### A001 `adapter-python-package`

A001 is the **applicability rule**: it decides whether the rest of this contract
has anything to say about a repository. It constrains no code, and at `notice`
severity it can never fail a build.

It is deliberately registered first and validated end to end before any rule that
constrains adapter code is added, so that a broken dispatch chain surfaces as a
loud, obvious failure instead of a silent no-op gate.

It reports when:

- `pyproject.toml` is missing — the repository is not a Python package at all;
- `pyproject.toml` cannot be parsed — the gate cannot tell, and says so rather
  than passing silently;
- the package declares no `dcc-mcp-core` dependency.

That last case is the interesting one. Four registered repositories currently
report it, and each is a genuine finding about the manifest rather than noise:

| Repository | Why |
|---|---|
| `dcc-mcp-cache-inspector` | `pyproject.toml` has no `[project]` table — a skill pack, not a package |
| `dcc-mcp-maya-procedural-architecture` | Skill pack; `[project]` exists but `dependencies` is empty |
| `dcc-mcp-runtime` | `dependencies = []` — a standalone runtime contract, not core-based |
| `dcc-mcp-epic` | Depends on `psutil` only; no `dcc-mcp-core` dependency |

They are registered anyway, because the sweep is how they were found and removing
them would hide the evidence. Correct the manifest (or the repository) and the
notice disappears.

#### How a declaration is recognised

The marker names and the places they may appear are read from the contract, not
hardcoded:

```json
"adapter_manifest_file": "pyproject.toml",
"adapter_marker_dependencies": ["dcc-mcp-core"],
"adapter_dependency_paths": [
  "project.dependencies",
  "project.optional-dependencies.*"
]
```

A trailing `.*` means "every group in this table", which is how optional groups
like `dev` and `semantic` are read without naming any of them. `dcc-mcp-core`
itself is in scope through its own optional groups.

Requirement strings are normalised before comparison, so `dcc_mcp_core`,
`DCC-MCP-CORE[extra]`, and `dcc-mcp-core>=0.20.36` all match the same marker. The
match is on the distribution name only — `dcc-mcp-coreutils` does **not** match.

## The ratchet

The plan is the same one the repository contract uses: land the gate, let the
warnings be the to-do list, then promote.

| Step | State | Owner |
|---|---|---|
| 1 | `A001` at `notice` in `baseline`; 50 repositories registered; dispatch proven | PIP-4105 (**done**) |
| 2 | Interface-layer rules land as `error` in `baseline` — no adapter may reference the deprecated `INSTALL_SOP_SCHEMA_VERSION` alias | PIP-4104 sub-issues |
| 3 | Code-style rules land as `warning` in `strict` — `line-length` converges on 120 | PIP-4104 sub-issues |
| 4 | A clean repository opts into `strict` and promotes rules with `error_rules` | per repository |

Step 2 is a hard `error` immediately because the correct API already exists in
core `0.20.40` and referencing the deprecated alias is statically decidable, with
no runtime risk. Step 3 starts as a warning because `line-length` is a preference
rather than a defect, and the sweep output is what makes the gap visible.

New rules should enter `strict` as warnings and be promoted once the sweep shows
the organisation is clean. Promoting a rule while repositories are still red
converts a to-do list into 50 failing builds, which is how gates get turned off.

## Relationship to the repository contract

| | `repo_contract.json` | `adapter_contract.json` |
|---|---|---|
| Rule namespace | `R0xx` | `A0xx` |
| Applies to | Every `dcc-mcp` repository | Python packages built on `dcc-mcp-core` |
| Asks | Is the repository configured and documented consistently? | Does the adapter use the shared platform API correctly? |
| Nightly sweep | `repo-contract-nightly.yml` | `adapter-contract-nightly.yml` |
| Manifest | `contract/repositories.json` | `contract/adapter_repositories.json` |
| Checker | `scripts/check_repo_contract.py` | the same script, with `--contract` |

The two are complementary, not ordered: a repository may be swept by both, and 11
of the 50 adapters already are. They answer different questions, so overlapping
registration is expected and produces no duplicate findings.

This document covers only what is specific to adapters. Profiles, severity
resolution, `--error-rule`, `--fail-on`, and the annotation format are documented
once, in [docs/repo-contract.md](repo-contract.md).

## Running it locally

```bash
# In an adapter repository, against a checkout of dcc-mcp/.github
python /path/to/dcc-mcp/.github/scripts/check_repo_contract.py \
  --contract /path/to/dcc-mcp/.github/contract/adapter_contract.json \
  --root . --profile baseline --format text

# What does the contract say?
... --contract .../adapter_contract.json --list-rules --profile baseline

# Rebuild the nightly matrix
... --contract .../adapter_contract.json --emit-matrix .../adapter_repositories.json
```

## Changing a rule

Edit `contract/adapter_contract.json` — not the script. Adding a rule means adding
a `rules` entry plus a handler in `RULES`; `tests/test_repo_contract.py` asserts
the two stay in sync, and asserts the `R0xx` and `A0xx` namespaces never overlap.

Every threshold, marker, and manifest path is read from the contract. Nothing
about what an adapter must do belongs in Python.
