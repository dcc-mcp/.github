# Adapter runtime and distribution policy

This policy separates a host's Python process from an external Python adapter
process. The host's product name is not sufficient evidence of the boundary.
For example, a native host plug-in can communicate with a separate Python
service. A host-Python adapter can also use a Rust server sidecar without
shipping a second Python interpreter.

## Dependency classes

| Class | Host Python | External adapter |
|---|---|---|
| Standard library | Use the host-supported Python version | Use the shared runtime's supported version |
| Host-owned modules | Supplied by the host, not installed with pip | Reach through the host bridge/driver; do not copy native modules |
| First-party Core/server | Explicit version/ABI-compatible dependency; the Rust server is not another Python interpreter | Shared runtime's compatible Core/server dependency |
| Mandatory third-party Python | Prohibited inside the host adapter | Justified bridge dependencies, managed in the shared runtime dependency set |
| Optional feature | Separate, explicitly activated boundary; never silently imported/bundled in default host runtime | Separate compatible extra/dependency set |
| Build/dev tools | Allowed only in build/test environment | Allowed only in build/test environment |

Do not replace a real library with an incomplete parser merely to remove a
dependency. Reuse a suitable first-party public API, or implement and test the
precise supported contract. Do not copy third-party code into the adapter.

## Source declaration checks

The existing adapter contract checker runs A030–A032 from
`contract/adapter_contract.json`; no second repository sweep is created.
The new checks use Python 3.11+ stdlib `tomllib` to avoid silently accepting
partial dependency declarations. Existing rules remain usable independently.

```toml
[tool.dcc-mcp.runtime]
mode = "host"
```

For an external adapter:

```toml
[tool.dcc-mcp.runtime]
mode = "external"
provider = "dcc-mcp-runtime"

[tool.dcc-mcp.runtime.third-party-reasons]
websocket-client = "OBS WebSocket host bridge"
```

| Check | Scope | Initial severity |
|---|---|---|
| A030 | Explicit execution mode for named `dcc-mcp-*` Python projects, excluding Core/runtime providers | strict warning |
| A031 | Mandatory PEP 621/Poetry dependencies for declared host adapters | strict warning |
| A032 | Official external provider and purpose of mandatory third-party dependencies | strict warning |

Markers do not exempt a dependency: it remains required on at least one target.
Extras and distribution names are normalized. Build/dev/optional groups are not
mistaken for mandatory runtime requirements. Dynamic dependency declarations
are reported as unknown and require inspection of built metadata. Legacy
`setup.py`-only and unnamed projects are outside this static declaration check;
they require artifact metadata and manual process-boundary review.

These rules are a **declaration gate**. They cannot prove that optional imports
are lazy, that a source vendor directory is clean, or that an external entry
point actually performs a handshake. Nor does declaring the official provider
prove an official platform interpreter has been released. Mixed host/service
packages must identify and independently test both runtime boundaries before
adopting a single package-level mode. Do not guess a mode to silence a warning.

Run the same gate as the nightly sweep:

```sh
python scripts/check_repo_contract.py --root ../adapter \
  --contract contract/adapter_contract.json --profile strict
```

Promote A030–A032 using the existing `error_rules` repository manifest field
or `--error-rule A030,A031,A032` only after the owning adapter passes source,
artifact and isolated/runtime acceptance checks. No fleet-wide errors or
automatic repository modifications are introduced by this policy.

## Artifact gate and measured size

```sh
python scripts/audit_runtime_artifact.py adapter.whl
python scripts/audit_runtime_artifact.py portable.zip \
  --mode host --adapter dcc-mcp-example
python scripts/audit_runtime_artifact.py external-adapter.tar.gz --mode external
```

The auditor never extracts, executes, imports, installs or downloads anything.
It streams every regular ZIP/wheel/tar member through EOF, validates its declared
size and the archive reader's integrity checks (including ZIP CRC and encryption),
and inspects bounded nested archives. It calculates SHA-256, exact archive bytes
and verified expanded bytes, lists distribution metadata, and reports the largest
members. Ordinary files are streamed without retaining their contents in memory.
The contract's `max_unpacked_bytes` limits all outer and nested expanded reads
combined; metadata and nested archive buffering retain their separate limits.
Nested expanded bytes are separate from the
outer archive's expanded bytes so the two are not incorrectly added together
as an installed footprint. Limits and detection patterns live in the contract.

`host` and `external` modes reject recognized interpreter and environment
payloads in an **adapter artifact**. The separate official runtime distribution
is intentionally inspected with the default `inspect` mode. Host mode also
rejects third-party distribution metadata; the exact adapter name must be
provided. Plain stdlib `venv/` is not evidence of a virtual environment.
Malformed metadata, unsafe/duplicate member paths, unreadable archives and
inspection limits fail instead of silently reducing coverage. Exit codes are
0 (no findings), 1 (findings/incomplete inspection), 2 (audit unavailable).
If `inspection_complete` is false, expanded byte counts cover only successfully
validated members and must not be presented as a complete artifact size. TAR
has no per-member CRC; these checks do not provide cryptographic authenticity.

This is not a security scanner or a complete import-closure proof. Renamed or
metadata-free vendored packages, opaque executable resources and unrecognized
compression formats can evade inventory. A clean result means only the stated
archive checks passed. Every migration still needs isolated startup, dependency
denial tests, host/API readback and real native-host acceptance as applicable.

## Shared runtime rollout gates

1. Verify supported OS/architecture/Python ABI, bridge behavior and Core floor.
2. Build the official runtime once per compatible dependency set, with exact
   package versions and a reproducible manifest. Keep incompatible sets separate.
3. Publish real target binaries and verify hashes/provenance. Do not fabricate
   hashes, repurpose template zero hashes or accept a platform label as evidence.
4. Resolve/reuse the runtime through its approved lifecycle. Installation and
   activation remain consent-gated; no automatic environment changes here.
5. Migrate one representative adapter, preserving rollback, then test startup,
   handshake, host integration and failure cases. Compare matching artifacts.
6. Expand only after representative acceptance and a real size comparison.

The [2026-10-17 inventory](runtime-distribution-audit-2026-10-17.md) records why a
fleet-wide external migration is currently premature. It is evidence, not a
permission to replace another owner's runtime or release workflow.
