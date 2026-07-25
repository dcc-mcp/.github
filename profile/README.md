<p align="center">
  <img src="./dcc-mcp-pipeline-banner.png" alt="DCC-MCP connects the complete film and game production pipeline">
</p>

<p align="center">
  English | <a href="./README_zh.md">中文</a>
</p>

# DCC MCP

**Skill-driven infrastructure for agents to operate real creative tools.**

DCC-MCP does not build or prescribe an agent. It connects agents to a growing
ecosystem of desktop DCCs, game engines, 2D tools, production systems, asset
providers, profilers, and custom studio hosts through shared discovery,
execution, safety, and operations contracts.

## Why this project exists

The shortest DCC agent demo asks a model to write and run a `mayapy`, `hython`,
or Blender Python script. A production pipeline cannot depend on getting the
right script from the model on every turn.

Repeated code generation costs tokens and makes results vary with the model,
prompt, and context. Adapter authors also end up rebuilding the same transport,
main-thread dispatch, validation, process lifecycle, instance routing, and
diagnostics for every host.

DCC-MCP moves that common engineering into one reusable framework:

| Layer | Shared capability |
| --- | --- |
| Integration | MCP and REST endpoints, Host RPC/IPC, typed schemas, resources, prompts, and structured results |
| DCC runtime | Main-thread affinity, readiness, multi-instance routing, async jobs, cancellation, checkpoints, workflows, and artefact hand-off |
| Skill delivery | Versioned `SKILL.md` packages, progressive discovery, lint/schema validation, hot reload, persistence, marketplace distribution, and project/team scopes |
| Operations | CLI, gateway, Admin UI, policies, audit records, traces, logs, metrics, health checks, and replay |

Agents and models will change. Studio interfaces, permission boundaries, and
pipeline knowledge still need to be maintained. The framework turns those
investments into reusable engineering assets.

## MCP is an entry point, not the ceiling

We reuse MCP as an industry-standard agent interface instead of inventing a
private protocol. The framework is not limited to MCP: a stable Python, C++,
HTTP, command-port, or native plugin interface can be integrated under the same
control plane.

We also include useful vendor capabilities instead of replacing them. Unreal
Engine 5.8 introduced an
[experimental official MCP server and Toolset Registry](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor).
Our
[`unreal-official-mcp` Skill](https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/src/dcc_mcp_unreal/skills/unreal-official-mcp/SKILL.md)
enables and bridges those official toolsets without redistributing Epic's
plugin or changing its tool names and schemas. Vendor tools, DCC-MCP tools, and
studio tools can share one agent-facing workflow.

### When there is no API: UI Control

Adding an AI-facing interface to a new tool is usually straightforward. The
harder problem is making years of existing tools usable by agents when they
have no API, cannot be modified, or expose part of a workflow only through a
window or modal dialog.

dcc-mcp-core provides a scoped Computer Use-style capability called **UI
Control**. It uses a deterministic `snapshot -> find -> act -> wait -> verify`
loop over Qt, native accessibility, webviews, or host-specific UI backends.
Native Skills/APIs remain preferred; whole-desktop access is denied by default,
and UI actions stay scoped, policy-checked, auditable, and verifiable. See the
[UI Control workflow guide](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/guide/app-ui-workflows.md).

## Why Skills are the production unit

A Skill is not just a script in another folder. It packages proven pipeline
knowledge as a versioned, typed, testable, and distributable operation.

A lower-cost model may struggle to invent scene-editing logic from scratch but
can reliably select a well-described tool and provide validated arguments.
Skills reduce repeated code generation, token use, and model-dependent
variance. Large studios can distribute different Skill sets by project,
department, and production stage without rebuilding an adapter.

For TDs and TAs, Skills are the shortest path from an internal requirement to
a reusable capability. Keep host connectivity, main-thread execution, routing,
safety, and observability in Core and the adapter; package project naming,
scene checks, asset preparation, publish gates, cache/export rules, and review
hand-offs in `SKILL.md`, `tools.yaml`, and existing studio scripts. The result
can be tested, project-scoped, and distributed through a public or private
Marketplace without forking the control plane.

## A growing ecosystem

| Area | Projects and Skills |
| --- | --- |
| Foundation and distribution | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core), [`marketplace`](https://github.com/dcc-mcp/marketplace) |
| Desktop DCCs | [Maya](https://github.com/dcc-mcp/dcc-mcp-maya), [Blender](https://github.com/dcc-mcp/dcc-mcp-blender), [Houdini](https://github.com/dcc-mcp/dcc-mcp-houdini), [3ds Max](https://github.com/dcc-mcp/dcc-mcp-3dsmax), [Nuke](https://github.com/dcc-mcp/dcc-mcp-nuke), [Katana](https://github.com/dcc-mcp/dcc-mcp-katana), [MotionBuilder](https://github.com/dcc-mcp/dcc-mcp-mobu), [ZBrush](https://github.com/dcc-mcp/dcc-mcp-zbrush) |
| Design and content tools | [Photoshop](https://github.com/dcc-mcp/dcc-mcp-photoshop), [Substance 3D Designer](https://github.com/dcc-mcp/dcc-mcp-substance3d-designer), [Substance 3D Painter](https://github.com/dcc-mcp/dcc-mcp-substance3d-painter), [After Effects](https://github.com/dcc-mcp/dcc-mcp-aftereffects), [Premiere](https://github.com/dcc-mcp/dcc-mcp-premiere), [GIMP](https://github.com/dcc-mcp/dcc-mcp-gimp), [Krita](https://github.com/dcc-mcp/dcc-mcp-krita) |
| Game and 2D engines | [Unreal Engine](https://github.com/dcc-mcp/dcc-mcp-unreal), [Unity](https://github.com/dcc-mcp/dcc-mcp-unity), [Godot](https://github.com/dcc-mcp/dcc-mcp-godot), [Tiled](https://github.com/dcc-mcp/dcc-mcp-tiled), [Material Maker](https://github.com/dcc-mcp/dcc-mcp-material-maker) |
| Pipeline and quality | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd), [Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt), [MaterialX](https://github.com/dcc-mcp/dcc-materialx), [Texture Pipeline](https://github.com/dcc-mcp/dcc-texture-pipeline), [Pipeline Publish](https://github.com/dcc-mcp/dcc-pipeline-publish), [RenderDoc](https://github.com/dcc-mcp/dcc-mcp-renderdoc), [Tracy](https://github.com/dcc-mcp/dcc-mcp-tracy) |
| Marketplace Skills | Assets, generation, UI, rigging, and game workflows |

The [official Marketplace](https://github.com/dcc-mcp/marketplace) makes those
optional capabilities searchable, installable, upgradeable, and suitable for
private studio catalogs too.

<!-- markdownlint-disable MD013 -->
[![DCC-MCP Skill Marketplace](https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-core/main/docs/assets/admin-ui/admin-marketplace.png)](https://github.com/dcc-mcp/marketplace)
<!-- markdownlint-enable MD013 -->

## Tool use should not be a black box

The Gateway Admin UI exposes calls, traces, logs, health, statistics, and usage
activity. Teams can see which tools agents selected, where calls failed, and
which Skills are used most often. That evidence can drive a practical feedback
loop: improve a description, schema, or implementation, then verify the result
against real calls.

## Start here

| Need | Project |
| --- | --- |
| Build an adapter or operate live DCC sessions | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core) |
| Discover and distribute reusable Skills | [`marketplace`](https://github.com/dcc-mcp/marketplace) |
| Explore the full ecosystem | [All DCC-MCP repositories](https://github.com/orgs/dcc-mcp/repositories) |
| Integrate game engines | [Unreal Engine](https://github.com/dcc-mcp/dcc-mcp-unreal), [Unity](https://github.com/dcc-mcp/dcc-mcp-unity), [Godot](https://github.com/dcc-mcp/dcc-mcp-godot) |
| Build pipeline integrations | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd), [Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt), [Texture Pipeline](https://github.com/dcc-mcp/dcc-texture-pipeline) |

Browse the [DCC-MCP repositories](https://github.com/orgs/dcc-mcp/repositories)
for more adapters, asset providers, UI automation, profilers, and production
Skills.

The boundary is deliberate: the core does not replace host-specific pipeline
semantics or promise safe rollback where a DCC exposes no transaction API.
Those responsibilities stay in adapters and pipeline Skills.

If you want DCC agents to move from demos to reusable, deployable, and
observable production tools, try the project and give it a Star.

## Contributing

Issues and pull requests are welcome. Please report bugs, integration gaps, and
production workflow needs in the relevant repository. Focused adapters, Skills,
tests, documentation, and interoperability improvements are especially useful.
