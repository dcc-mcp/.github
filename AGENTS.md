# AGENTS.md

Instructions for coding agents working in `dcc-mcp/.github`, the organisation
default repository. It holds the org profile, the reusable CI gates, and the
repository contract that every `dcc-mcp` repository is checked against.

## What lives where

| Path | Purpose |
|---|---|
| `profile/` | The public `dcc-mcp` GitHub organisation profile. Checked by `scripts/check_profile_contract.py`. |
| `contract/repo_contract.json` | Machine-readable repository contract (`R0xx`): rules, severities, root allowlist. **Single source of truth.** |
| `contract/adapter_contract.json` | Machine-readable Python adapter contract (`A0xx`): interface and code-convention rules. **Single source of truth.** |
| `contract/repositories.json` | Manifest of repositories swept nightly by the `R0xx` contract gate. |
| `contract/adapter_repositories.json` | Manifest of the 50 Python package repositories swept nightly by the `A0xx` contract gate. |
| `scripts/check_*.py` | The gates. Stdlib-only, no third-party imports. |
| `tests/` | `unittest` suites, run with `python -m unittest discover -s tests -v`. |
| `.github/workflows/` | Reusable (`workflow_call`) workflows plus the org-wide nightly sweeps. |
| `docs/repo-contract.md` | Rules, severities and the ratchet for the `R0xx` contract. |
| `docs/adapter-contract.md` | The same for the `A0xx` contract, plus where the boundary between the two sits. |

## Non-negotiables

- **Stdlib only in `scripts/` unless a `requirements-*.txt` says otherwise.**
  `check_profile_contract.py` is the one exception and declares
  `markdown-it-py` in `requirements-profile-check.txt`.
- **Never hardcode a rule, threshold, or allowlist in a script.** They belong in
  the JSON under `contract/`. The contract is also consumed by the
  `vx-repo-contract` skill, so a criterion written in Python here would silently
  diverge from what developers run locally.
- **One rule namespace per contract.** `repo_contract.json` owns `R0xx` and
  `adapter_contract.json` owns `A0xx`; both are loaded by the same checker via
  `--contract`, so a new rule needs an id in the namespace of the contract it
  belongs to. `tests/test_repo_contract.py` asserts the two stay disjoint.
- **A rule is text-visible or it is not a rule.** The `A0xx` interface rules run
  on the syntax tree, not on a grep of the source: six repositories document in
  comments and regression tests *why* Core's deprecated alias must not be used,
  and a text match would report those as violations.
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
python scripts/check_repo_contract.py --root . --contract contract/adapter_contract.json --profile strict
```

The second command must report no errors. The third runs the adapter contract
against this repository: it is not a Python package, so A005 and A006 warn
about the missing `pyproject.toml` and pre-commit config. Two warnings and exit
0 is the expected result; anything else means the checker regressed. If you
change either contract file, explain the severity change in the PR description —
it affects every repository that has adopted the gate.
