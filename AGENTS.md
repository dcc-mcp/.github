# AGENTS.md

Instructions for coding agents working in `dcc-mcp/.github`, the organisation
default repository. It holds the org profile, the reusable CI gates, and the
repository contract that every `dcc-mcp` repository is checked against.

## What lives where

| Path | Purpose |
|---|---|
| `profile/` | The public `dcc-mcp` GitHub organisation profile. Checked by `scripts/check_profile_contract.py`. |
| `contract/repo_contract.json` | Machine-readable repository contract: rules, severities, root allowlist. **Single source of truth for the `R0xx` rules.** |
| `contract/repositories.json` | Manifest of repositories swept nightly by the contract gate. |
| `contract/adapter_contract.json` | The adapter contract: rules that only apply to the Python adapter packages. Ids use the **`A0xx`** namespace so they can never collide with `R0xx`. Selected with `--contract`. |
| `contract/adapter_repositories.json` | Manifest of the Python adapter packages swept nightly by `adapter-contract-nightly.yml`. |
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
that has adopted the gate.
