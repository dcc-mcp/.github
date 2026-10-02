# Adapter contract

A mechanical gate for the conventions that every `dcc-mcp-*` Python adapter
package is expected to follow. It exists because the conventions were written
down and then drifted: `line-length` settled on three different values,
`requires-python` on four, and only a handful of repositories ran the checks
locally at all.

The rules and their thresholds are defined once, in
[`contract/adapter_contract.json`](../contract/adapter_contract.json). The CI
gate ([`scripts/check_repo_contract.py`](../scripts/check_repo_contract.py), run
with `--contract`) and the `vx-repo-contract` skill both read that file, so a
criterion is never written down twice.

The rule handlers live in
[`scripts/adapter_contract_rules.py`](../scripts/adapter_contract_rules.py), one
module per rule family, so that each family lands as an additive change rather
than as five agents editing the middle of one file.

## Boundary with the repository contract

| | `repo_contract.json` | `adapter_contract.json` |
|---|---|---|
| Applies to | every repository in the org | repositories that publish a `dcc-mcp-*` Python package |
| Rule ids | `R0xx` | `A0xx` |
| Covers | layout, `vx.toml`, `AGENTS.md`, generated docs | Python packaging and code-style configuration |
| Decided by | PIP-3741 and its follow-ups | PIP-4104 and its follow-ups |

The two contracts are siblings, not layers. A repository that adopts both runs
the checker twice; neither file changes the meaning of the other, and adding an
adapter rule never tightens a non-Python repository such as `loonghao/vx`.

## Running it

```bash
python scripts/check_repo_contract.py \
  --contract contract/adapter_contract.json \
  --root ../dcc-mcp-maya \
  --profile strict \
  --fail-on warning
```

`--fail-on warning` is how the nightly sweep turns the output into a to-do list.
Promote a single rule with `--error-rule A020` once a repository is clean.

## Rules

| Id | Rule | `baseline` | `strict` | Decided by |
|---|---|---|---|---|
| A020 | `ruff-line-length` — `[tool.ruff] line-length` is the org baseline (120) | — | warning | PIP-4107 |
| A021 | `ruff-config-present` — the repository configures ruff at all | — | warning | PIP-4107 |
| A022 | `pre-commit-present` — a pre-commit configuration exists | — | warning | PIP-4107 |
| A023 | `requires-python-declared` — `pyproject.toml` declares `requires-python` | — | warning | PIP-4107 |
| A024 | `release-please-present` — release-please config and manifest exist | — | warning | PIP-4107 |

The whole family starts as `strict`-only warnings. `baseline` deliberately
selects nothing yet: the backlog below is closed by ratchet, not by an error
that breaks fifty CI pipelines on the same afternoon.

### What each rule judges

**A020** reads `line-length` from the first ruff configuration the repository
has — a standalone `ruff.toml` or `.ruff.toml` wins, then `[tool.ruff]` in
`pyproject.toml`, which is the order ruff itself resolves them in. A `[tool.ruff]`
section that never says `line-length` is reported too: ruff would silently fall
back to its own default of 88, and that silence is the drift. When the
repository has no ruff configuration at all A020 stays quiet, because A021
already reports that gap and one gap should produce one finding.

**A021** is the premise for the rest: without a ruff configuration, formatting
and lint settings differ between a developer machine and CI.

**A022** accepts either `.pre-commit-config.yaml` or `.pre-commit-config.yml`.
It is the premise for enforcing anything locally — without a hook, the feedback
cycle for a convention moves from seconds to minutes.

**A023** checks that `requires-python` is **declared**, deliberately not what it
declares. Hosts have legitimate differences (zbrush, wwise and obs need 3.10;
the org Python 3.7 red line in PIP-2519 runs to 2026-12-31), so the value stays
a per-host decision until that red line is lifted. This rule only removes the
case where nothing is said at all and pip happily installs the package on an
interpreter it cannot work on.

**A024** requires every file in `release_please_files`, reporting each missing
one separately so the annotation points at the file to add.

Values that are not judged are still visible in the finding messages: the
nightly output is the backlog list, and every message says what to do next.

## Measured backlog (2026-10-02)

Measured by running the rules against all fifty registered adapter
repositories. Where this disagrees with the hand survey in PIP-4104, the
difference is explained below — the rules read the files, so they are the
current figure.

| Rule | Repositories | Note |
|---|---|---|
| A020 | 30/50 | all of them at `line-length = 100`; the other 15 declare 120 |
| A021 | 4/50 | `dcc-mcp-powerpoint`, `dcc-mcp-openscreen`, `dcc-mcp-gaea` have a `pyproject.toml` without `[tool.ruff]`; `fpt-cli` has no `pyproject.toml` at all |
| A022 | 44/50 | pre-commit exists in core, maya, unreal, photoshop, houdini and fpt |
| A023 | 1/50 | `dcc-mcp-cache-inspector` |
| A024 | 1/50 | `dcc-mcp-cache-inspector`, missing both files |

PIP-4104 estimated "about 44/50" repositories with a ruff configuration and
"48/50" with release-please; the rules measure 46/50 and 49/50. The hand survey
was taken before the newest repositories were published, and this table is
generated from the repositories as they stand.

The `110` value PIP-4104 recorded for `line-length` belongs to `dcc-itchio`,
which is not one of the fifty Python-package repositories — within the
registered set only `100` and `120` occur. It stays an open question for the
product owner: either it becomes a recorded exception in the contract or the
repository reformats to 120.

## Ratchet

1. The family lands as `strict`-only warnings and is added to the nightly sweep
   with `--profile strict --fail-on warning`. The output is the backlog.
2. Each repository closes its own warnings. Reformatting is deliberately kept
   out of this work — it produces a huge diff and belongs in its own change.
3. A rule moves from `strict` to `baseline` only when the count above is zero.
4. A warning becomes an error with `--error-rule`, or by moving the rule's
   severity in the contract once every registered repository is clean.
