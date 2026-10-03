# Adapter contract

A mechanical gate for the Python adapter contract agreed in PIP-4104. It exists
because the 50 dcc-mcp repositories that ship a Python package have been
converging by hand for months: the same Install SOP report field has been
written five different ways, `line-length` has three values, and nothing
stopped any of it coming back after the last cleanup.

The rules and their severities are defined once, in
[`contract/adapter_contract.json`](../contract/adapter_contract.json). The CI
sweep ([`scripts/check_repo_contract.py`](../scripts/check_repo_contract.py)
with `--contract`) reads that file, so a criterion is never written down twice.

## Boundary with the repository contract

| | [`repo_contract.json`](repo-contract.md) (`R0xx`) | `adapter_contract.json` (`A0xx`) |
|---|---|---|
| Applies to | every repository in the sweep | the 50 repositories that ship a Python package |
| Subject | configuration and documentation hygiene | Python interface surface and code conventions |
| Manifests | [`contract/repositories.json`](../contract/repositories.json) | [`contract/adapter_repositories.json`](../contract/adapter_repositories.json) |
| Sweep | `repo-contract-nightly.yml` | `adapter-contract-nightly.yml` |

Both contracts are loaded by the **same checker**, selected with `--contract`,
and both use the same `baseline` / `strict` profiles. Rule ids are namespaced
precisely so that the two can be listed side by side in one job without a
collision; `tests/test_repo_contract.py` asserts the namespaces stay disjoint.

A rule belongs in `adapter_contract.json` only when it needs a Python package to
be meaningful. "No build artifacts at the root" is true of every repository and
stays in `repo_contract.json`; "`[tool.ruff] line-length` is 120" means nothing
without a `pyproject.toml` and belongs here.

## Rules

| Id | Rule | `baseline` | `strict` | Kind |
|---|---|---|---|---|
| A001 | `no-deprecated-install-sop-alias` — no reference to Core's deprecated `INSTALL_SOP_SCHEMA_VERSION` | error | error | interface |
| A002 | `no-hand-rolled-report-schema-version` — no locally hard-coded `*_REPORT_SCHEMA_VERSION` | — | warning | interface |
| A003 | `core-floor-declared` — a declared `dcc-mcp-core` dependency pins a lower bound | error | error | interface |
| A012 | `core-floor-baseline` — the declared floor is at or above the organisation baseline | — | warning | interface |
| A004 | `ruff-line-length` — `[tool.ruff] line-length` is `120` | — | warning | convention |
| A005 | `requires-python-declared` — `project.requires-python` is declared | — | warning | convention |
| A006 | `pre-commit-config-exists` — `.pre-commit-config.yaml` is present | — | warning | convention |
| A013 | `doctor-module-present` — an adapter that installs ships a `doctor` self-check | — | warning | interface |
| A014 | `report-validates-against-schema` — a real report runs through `validate_install_sop_report()` | — | warning | interface |

Ids A007–A012 are unassigned on purpose. The Install SOP interface family was
numbered A010–A014 by PIP-4106 before A001–A006 existed; three of those five
rules were already covered here as A001, A002 and A003 when the family was
landed, so only the two that were not — the `doctor` module and the report
validation — were added, under their original ids.

### Why A001 can be an error on day one

Core 0.20.40 (PIP-4080) renamed `INSTALL_SOP_SCHEMA_VERSION` to
`INSTALL_SOP_SCHEMA_REVISION` and kept the old name as a `__getattr__` alias
that raises `DeprecationWarning`. The two names are not the same quantity: the
old one is the revision of the published schema **artifact** (`-vN`), while a
report's `schema_version` field is the schema document's `const`, which stays
at 1. The values agreed at 1 until Core 0.20.34 republished the artifact as
`-v2` — which is how six repositories ended up emitting `2` where the schema
requires `1` (PIP-4047 / 4048 / 4049 / 4050 / 4051).

The rule is safe to enforce immediately, without raising any Core floor,
because every existing reference already sits behind a `try/except ImportError`
fallback written for old Core releases. Deleting the reference deletes code that
cannot be reached on any Core the repository already supports.

**The fix depends on what the value means**, and the two cases need opposite
edits:

- The value means the **artifact revision** — a field named
  `schema_artifact_revision`, a constant named `ARTIFACT_SCHEMA_VERSION`. The
  value is already correct and only the name is deprecated, so **rename** it to
  `INSTALL_SOP_SCHEMA_REVISION`. This is the case in 8 of the 12 repositories
  that report A001 today.
- The value feeds a report's **`schema_version`** field, or is a vestigial
  import that nothing reads. **Delete** the reference and read the field from
  `install_sop_report_schema_version()`.

**Never rename to make the gate go green.** Where the value reaches a
report's `schema_version`, renaming keeps the artifact revision flowing into a
field the schema pins at `1` — the defect survives the rename and becomes harder
to spot (PIP-3990's root cause). `dcc-mcp-sketchup` is that case today:
`return declared if isinstance(declared, int) else INSTALL_SOP_SCHEMA_VERSION`
silently publishes the artifact revision whenever the schema cannot be read.

#### What counts as a reference

The check runs on the **syntax tree**, not on text, so comments and docstrings
are invisible to it. Three shapes are reported:

```python
from dcc_mcp_core.deployment import INSTALL_SOP_SCHEMA_VERSION   # 1. import
INSTALL_SOP_SCHEMA_VERSION = 1                                   # 2. local rebinding
revision = dcc_mcp_core.deployment.INSTALL_SOP_SCHEMA_VERSION    # 3. attribute access
```

The second shape matters: the `except ImportError` fallback exists only to
support the import, and an `__all__` re-export keeps the deprecated name in the
adapter's own public surface. Both must go with the import.

Two exclusions are deliberate and live in the contract, not in the script:

- **Test directories are out of scope** (`scan_exclude_dirs`). The regression
  tests that assert the alias is *not* used have to be able to name it:
  `test_report_schema_version_ignores_cores_artifact_revision` monkeypatches
  `INSTALL_SOP_SCHEMA_VERSION` to `2` on purpose. Scanning tests would force
  those guards to be rewritten or deleted to satisfy the gate.
- **The provider may define and export the alias** (`provider_package_dirs`).
  `dcc-mcp-core` owns the deprecated name; the rule targets its consumers. This
  is why `dcc-mcp-core` can sit in the same sweep as its 49 consumers without a
  per-repository exemption.

This distinction is why the check is AST-based rather than a grep. A GitHub code
search for `INSTALL_SOP_SCHEMA_VERSION` reports 18 hits across the organisation
and names only 3 repositories; the sweep finds **12**, and all 12 are real code
references. Code search both under-reports (it missed `dcc-mcp-marmoset`,
`dcc-mcp-wwise` and six others entirely) and over-reports (15 of its 18 hits are
comments, docstrings and test guards explaining *why* the alias must not be
used). Neither direction is usable as a gate.

### Why A002 is a warning

Every hand-rolled `FALLBACK_REPORT_SCHEMA_VERSION = 1` is a second source of
truth for the schema `const` — 13 of them across 12 repositories today.
Converging on
`install_sop_report_schema_version()` first needs the repository's Core floor
raised to `>=0.20.40`, because that is the release the API landed in — and the
highest floor any repository declares today is `>=0.20.36` (autocad, cinema4d,
freecad, openscad, sketchup). Raising 50 floors is PIP-4101's job, not this
gate's, so the rule reports the gap and does not fail on it.

### Why A012 separates a baseline from a target

A003 makes a lower bound mandatory. A012 answers the separate question of
whether the bound is *high enough*, and it carries two numbers because the two
questions it has to serve have different answers:

```json
"core_floor_baseline": "0.20.36",
"core_floor_target": "0.20.40"
```

`core_floor_baseline` is the highest floor any adapter already declares, so the
target is reachable on the day the rule lands rather than aspirational. That is
not a stylistic preference — it is what makes the finding a signal. Measured
2026-10-03 over the 45 repositories that declare a Core floor:

| Verdict | Count | Repositories |
|---|---|---|
| warning (below `0.20.36`) | **40** | floors from `>=0.18.2` (powerpoint) to `>=0.20.34` (premiere) |
| notice (at `0.20.36`, below `0.20.40`) | **5** | autocad, cinema4d, freecad, openscad, sketchup |
| pass (at or above `0.20.40`) | **0** | — |

Had the baseline been set at `0.20.40`, all 45 would have warned and the rule
would have said nothing about which repository is furthest behind. At `0.20.36`
it ranks the fleet: the 40 warnings are a backlog ordered by how far each
repository has drifted, and the 5 notices are the repositories that are one
bump away.

`core_floor_target` is where the shared Install SOP API
(`install_sop_report_schema_version()`, `validate_install_sop_report()`) becomes
unconditionally available. Sitting above the baseline but short of the target is
a **notice**, which is reported but can never fail a run: it is the reason A002
cannot be promoted to an error yet, not a defect in its own right.

A Core dependency that pins no bound at all is left to A003. One gap, one
finding.

### Why A013 and A014 are warnings

Both rules describe a gap that is expensive to close rather than a defect, so
they report without failing. 8 of the 50 swept adapters ship a `doctor` module
today (openusd, material-maker, wwise, freecad, sketchup, openscad, liquigen,
capcut), and A013 flags **28** of the 45 packages the sweep could read. A014 is
the sharper of the two: it flags **27**, including five of those eight
(capcut, material-maker, openscad, sketchup, wwise), because a doctor that
assembles a report is not the same thing as a doctor that validates one. Both
columns are PIP-4101's work queue.

Both rules are scoped to repositories that actually have an install surface —
one of the `install_sop_symbols` appearing in a scanned module, or a module
matching `install_source_globs`. Repositories with no install capability are
skipped rather than reported, so the rule set stays silent for the packages it
was never written for.

Both are matched by name or by text, which makes them satisfiable in the letter
without being satisfied in spirit: a `doctor` that never validates a report
passes A013, and a `# TODO: use validate_install_sop_report` in a workflow
passes A014. That is the right trade for a warning — a noisy gate gets switched
off, while a permissive one still points at the right file — and it is why
neither rule belongs in `baseline` until the ratchet closes the gap.

### Why A005 does not pick a value

`requires-python` has four legitimate values in the fleet (`>=3.7` through
`>=3.10`) plus one repository that declares none, because host-side constraints
differ: zbrush, wwise and obs need `>=3.10` for the host bridge, while the
organisation Python 3.7 red line (PIP-2519) holds until **2026-12-31**. The rule
therefore checks only that the range is *visible to pip*, and leaves the value
to the host.

## The two-tier profile

`baseline` holds A001 and A003. Both are mechanical, both are satisfied by
every repository today or by a small, safe edit, and neither needs a Core floor
bump. Anything that needs a decision goes into `strict` as a warning.

That is the ratchet, the same one `repo-contract.md` describes: the sweep runs
`--profile strict --fail-on error`, so **errors block regressions and warnings
are the stock-take list**. A repository adopts the gate before it is clean, and
the warning column is the work queue.

Measured 2026-10-02 by running the checker over shallow clones of all 50
repositories:

| Rule | Repositories | Notes |
|---|---|---|
| A001 | 12 | 8 use the alias as an artifact revision (rename), 4 feed it into a report field or import it vestigially (delete) |
| A002 | 12 | 13 hard-coded constants in total |
| A003 | 0 | 45 of 50 declare a Core dependency with a lower bound; the other 5 declare none and are skipped (`dcc-mcp-cache-inspector`, `dcc-mcp-epic`, `dcc-mcp-maya-procedural-architecture`, `dcc-mcp-runtime`, and `dcc-mcp-core`, which owns the distribution) |
| A004 | 33 | 30 declare `line-length = 100`, 3 declare none |
| A005 | 1 | `dcc-mcp-cache-inspector` |
| A006 | 44 | 6 have a `.pre-commit-config.yaml` |
| A012 | 40 | plus 5 notices; see below |
| A013 | 28 | measured 2026-10-03 over the 45 repositories that cloned (see below) |
| A014 | 27 | includes 5 of the 8 that already ship a `doctor` module |

The A001–A006 rows were measured 2026-10-02 over all 50 repositories. The A013
and A014 rows were measured 2026-10-03 over the same sweep; five repositories
failed to clone in that run (`dcc-mcp-cache-inspector`,
`dcc-mcp-marvelous-designer`, `dcc-mcp-maya-procedural-architecture`,
`dcc-mcp-substance3d-designer`, `dcc-mcp-substance3d-painter`), so those two
counts are a lower bound over 45 packages.

`dcc-mcp-core` reports nothing under A001–A006: it owns the deprecated alias, so
`provider_package_dirs` exempts its package tree. It does report A013, because
it ships install machinery and no `doctor` module of its own.

Two repositories carry a file that does not parse as Python at all —
`dcc-mcp-3dsmax/import_balls_fbx.py` (a `for` statement with no body) and
`dcc-mcp-openscreen/.../scripts/_client.py` (literal `\n` sequences written into
the source). Both are reported as **notices** rather than skipped silently: a
file the gate cannot read is a gap in the gate, and the point of this contract
is that gaps are visible.

## Ratchet plan

Promote a rule with `--error-rule` in the manifest entry of every repository
that is clean, then move the promotion into the contract default. Concretely:

1. **A001/A003** — already errors. A001 needs no Core floor change, so it is
   the cheapest rule to clear: 8 of the 12 repositories are a one-line rename to
   `INSTALL_SOP_SCHEMA_REVISION`, and the other 4 delete a vestigial import. Do
   this first, because A001 is the only rule whose nightly output is red today.
2. **A004** — raise the 30 repositories on `line-length = 100` to `120` and
   declare it in the 3 that omit it. Reformatting is one `ruff format` run per
   repository; it belongs in a dedicated PR so it does not bury review signal.
3. **A002** — blocked behind PIP-4101: raise the Core floor to `>=0.20.40`,
   replace the hand-rolled constant with `install_sop_report_schema_version()`,
   then promote.
4. **A006 / A005** — cheapest to land, and worth doing early: a
   `.pre-commit-config.yaml` turns every later convention rule into something a
   contributor sees before pushing.

A006 and A005 are last in the dependency order but first in the value order.

## Adopting the sweep

Add the repository to
[`contract/adapter_repositories.json`](../contract/adapter_repositories.json)
and `adapter-contract-nightly.yml` picks it up the next morning — no workflow
file in the repository itself, the same way `repo-contract-nightly.yml` works.
Every repository that ships a Python package belongs in that manifest whether or
not it is clean.

## Running it locally

```bash
# The whole adapter contract, warnings and all
python /path/to/dcc-mcp/.github/scripts/check_repo_contract.py \
  --root . \
  --contract /path/to/dcc-mcp/.github/contract/adapter_contract.json \
  --profile strict \
  --format text

# Just the gate that CI fails on
... --profile baseline --fail-on error

# What does the contract actually say?
... --contract .../adapter_contract.json --list-rules --profile strict
... --contract .../adapter_contract.json --emit-contract
```

Findings are emitted as GitHub annotations
(`::error file=src/dcc_mcp_maya/install.py,title=Repo contract A001::...`) so
they land on the file in the diff.

## Changing a rule

Edit `contract/adapter_contract.json` — not the script. The script only
implements the mechanics (parse TOML, walk the tree, parse `pyproject.toml`) and
reads every threshold, symbol name, glob and severity from the contract. That is
what keeps `scripts/` free of hardcoded policy, and it is what lets a
repository's local `vx-repo-contract` run and CI agree.

Adding a rule means a `rules` entry plus a handler in `RULES`;
`tests/test_repo_contract.py` asserts the two stay in sync for both contracts.

## Deliberately not covered

- **Host-side language implementations** — SketchUp's Ruby bridge, C4D's
  `c4dpy`, the `dotnet` tree in `dcc-mcp-office`. The contract constrains the
  Python interface surface only.
- **`doctor` and `compat` module coverage** (8/50 and 5/50 today). Both are
  capability questions, not interface-contract questions, and capability
  standards are being defined separately in PIP-3974 (S1–S6). Adding a rule here
  would set the bar before that work has decided what the bar is.
- **A single `requires-python` value** — see above.
- **CI workflow count and shape** (1 to 23 workflows per repository). The spread
  is real but the target is not agreed; a rule would only encode a guess.
