# AGENTS.md

Instructions for coding agents working in `dcc-mcp/.github`, the organisation
default repository. It holds the org profile, the reusable CI gates, and the
repository contract that every `dcc-mcp` repository is checked against.

## What lives where

| Path | Purpose |
|---|---|
| `profile/` | The public `dcc-mcp` GitHub organisation profile. Checked by `scripts/check_profile_contract.py`. |
| `contract/repo_contract.json` | Machine-readable repository contract: rules, severities, root allowlist. **Single source of truth.** |
| `contract/adapter_contract.json` | Machine-readable adapter contract: rules for Python packages built on `dcc-mcp-core`. Rule ids live in the `A0xx` namespace, disjoint from `R0xx`. Same single-source-of-truth rule. |
| `contract/repositories.json` | Manifest of repositories swept nightly by the contract gate. |
| `contract/adapter_repositories.json` | Manifest of Python package repositories swept nightly by the adapter contract gate. |
| `docs/repo-contract.md` | The repository contract: rules, profiles, local usage. |
| `docs/adapter-contract.md` | The adapter contract: scope, ratchet plan, and how it relates to the repository contract. |
| `scripts/check_*.py` | The gates. Stdlib-only, no third-party imports. |
| `tests/` | `unittest` suites, run with `python -m unittest discover -s tests -v`. |
| `.github/workflows/` | Reusable (`workflow_call`) workflows plus the org-wide nightly sweeps. |

## Non-negotiables

- **Stdlib only in `scripts/` unless a `requirements-*.txt` says otherwise.**
  `check_profile_contract.py` is the one exception and declares
  `markdown-it-py` in `requirements-profile-check.txt`.
- **Never hardcode a rule, threshold, or allowlist in a script.** They belong in
  the JSON under `contract/`. The contract is also consumed by the
  `vx-repo-contract` skill, so a criterion written in Python here would silently
  diverge from what developers run locally.
- **`R0xx` and `A0xx` rule ids must never collide.** `check_repo_contract.py`
  implements one `RULES` table shared by both contracts, so an id reused across
  `contract/repo_contract.json` and `contract/adapter_contract.json` would let one
  contract silently redefine the other's rule. Adding a rule means adding a
  `rules` entry in the right contract plus a handler in `RULES`.
- **New adapter rules are scoped by A001.** Read `ctx["adapter_applicable"]`
  before reporting, so repositories that are not Python packages built on
  `dcc-mcp-core` stay silent instead of emitting findings that do not apply to
  them.
- **Reusable workflows must keep `workflow_call` and `workflow_dispatch` inputs
  in sync.** Adopting repositories call them through `workflow_call`; humans
  trigger them through `workflow_dispatch`.
- **Two checkouts, sibling directories.** A gate that inspects the repository
  root must check out the repository under test and the tooling into *different*
  directories (`repository/` and `contract-tooling/`), otherwise the tooling
  itself shows up as an un-allowlisted top-level entry.
- **This repository is checked by its own gate.** `AGENTS.md` is required by
  rule R003; do not delete it.

## Before opening a PR

```bash
python -m unittest discover -s tests -v
python scripts/check_repo_contract.py --root . --profile strict
```

The second command must be clean. If you change `contract/repo_contract.json`,
explain the severity change in the PR description — it affects every repository
that has adopted the gate. The same applies to `contract/adapter_contract.json`,
which additionally must keep its rule ids inside the `A0xx` namespace.
