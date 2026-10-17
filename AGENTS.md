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

## Adapter runtime and distribution gate

- Classify the **actual Python process**, not the product name. Host-interpreter
  adapters use the host's supported Python, stdlib, host-owned modules and the
  explicitly approved first-party Core/server distributions. Do not add third-party
  runtime requirements, copy their source into a vendor directory, or hide them
  in a ZIP. A Rust sidecar does not change the host Python dependency boundary.
- External adapters use the official `dcc-mcp-runtime` distribution. Do not
  create another per-adapter CPython, virtual environment or environment manager.
  Thin host scripts plus an external service need **two** audited import
  boundaries; a Python-capable host does not make its external service embedded.
- Separate stdlib, host modules, first-party Core/server, mandatory third-party bridge
  dependencies, optional features, and build/dev tools. Optional/build/dev
  labels never authorize importing or bundling those packages in the default
  host runtime. Keep host-owned modules out of pip dependencies.
- Shared means compatible, versioned reuse, not a process-global environment:
  scope by OS, architecture, Python ABI, Core version and dependency set. Keep
  incompatible sets side by side and preserve rollback. Never inject another
  interpreter or native ABI into a host to make a dependency resolve.
- Before migration, check active owners/PRs, existing Core/CLI/runtime APIs and
  actual released artifacts. Do not claim the Python runtime wheel includes
  CPython. An absent target binary, placeholder hash, stale manifest or untested
  host is a blocker, not permission to invent metadata or install automatically.
- Run A030–A032 and the read-only artifact auditor described in
  [the runtime policy](docs/adapter-runtime-policy.md). Source declarations and
  archive metadata are bounded checks, not proof of complete import closure.
  Each adapter must also run isolated no-site-packages startup/provenance tests
  and its real-host tests before promotion to a blocking gate.
- Report compressed bytes, expanded bytes, largest components and exact
  tag/SHA. Compare like-for-like platform/build artifacts and separately account
  for a shared runtime's first download and incremental adapters. Never claim
  savings from a hypothetical runtime or from deleting required host/Core code.

## Validation before opening a PR

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
