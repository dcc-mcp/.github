<!-- markdownlint-disable MD013 MD033 MD041 -->

<p align="center">
  <img src="./dcc-mcp-pipeline-banner.png" alt="DCC-MCP connects the complete film and game production pipeline">
</p>

<p align="center">
  English | <a href="./README_zh.md">中文</a>
</p>

# DCC MCP

**Skill-driven infrastructure for agents to operate real creative tools.**

DCC-MCP (Digital Content Creation Model Context Protocol) does not build or
prescribe an agent. It connects agents to a growing ecosystem of desktop DCCs,
game engines, 2D tools, production systems, asset providers, profilers, and
custom studio hosts through shared discovery, execution, safety, and operations
contracts.

## Agent entry points

Install the public Skill that matches the task. Operating an existing DCC only
needs `dcc-mcp`; the creator Skills are focused authoring guides.

| Agent task | Public Skill |
| --- | --- |
| Operate live DCCs, discover tools, install extensions, diagnose failures, and prepare safe bug reports | [`@loonghao/dcc-mcp`](https://clawhub.ai/loonghao/skills/dcc-mcp) |
| Create or modernize a complete DCC-MCP adapter and runtime | [`@loonghao/dcc-mcp-creator`](https://clawhub.ai/loonghao/skills/dcc-mcp-creator) |
| Create, validate, or improve a DCC-specific Skill package | [`@loonghao/dcc-mcp-skills-creator`](https://clawhub.ai/loonghao/skills/dcc-mcp-skills-creator) |

```bash
openclaw skills install @loonghao/dcc-mcp
openclaw skills install @loonghao/dcc-mcp-creator
openclaw skills install @loonghao/dcc-mcp-skills-creator
# Direct ClawHub CLI for other Agent Skills hosts:
npx --yes clawhub@0.23.1 install @loonghao/dcc-mcp
npx --yes clawhub@0.23.1 install @loonghao/dcc-mcp-creator
npx --yes clawhub@0.23.1 install @loonghao/dcc-mcp-skills-creator
```

Start a new agent turn after installation. The default workflow is
`dcc-mcp` + `dcc-mcp-cli`: inventory with `dcc-mcp-cli list`, inspect startup
state with `dcc-mcp-cli doctor`, then `search -> describe -> call`. The Skill
also teaches the agent to preserve trace evidence, analyze the failing layer,
and route a sanitized bug report to the owning Skill, adapter, or Core project.
Use the
[`dcc-mcp-cli` verified installation guide](https://github.com/dcc-mcp/dcc-mcp-core#quick-start-operate-a-dcc)
when the CLI is not already available.

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
[UI Control workflow guide](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/guide/ui-control-workflows.md).

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

### Extension Skill catalog

The [official catalog](https://github.com/dcc-mcp/marketplace/blob/main/marketplace.json)
currently publishes all of the following optional capabilities. Agents should
search the live catalog before installation:

```bash
dcc-mcp-cli marketplace search --query "<capability>" --limit 20
dcc-mcp-cli marketplace install <package_name> --dcc <dcc_name>
```

#### Rigging, procedural authoring, and UI automation

| Extension Skill | Capability |
| --- | --- |
| [`dcc-mcp-maya-mgear`](https://github.com/dcc-mcp/dcc-mcp-maya-mgear) | Inspect, build, and manage mGear Shifter rigs in Maya |
| [`dcc-mcp-maya-advancedskeleton`](https://github.com/dcc-mcp/dcc-mcp-maya-advancedskeleton) | Inspect templates and create, import, build, or rebuild AdvancedSkeleton rigs |
| [`dcc-mcp-maya-procedural-architecture`](https://github.com/dcc-mcp/dcc-mcp-maya-procedural-architecture) | Generate seeded Maya house styles with Arnold materials and optional CC0 HDR lighting |
| [`dcc-ui-qt-inspector`](https://github.com/dcc-mcp/dcc-ui-qt-inspector) | Discover Qt windows, widgets, and selector state across PySide/PyQt DCC hosts |
| [`dcc-ui-qt-actions`](https://github.com/dcc-mcp/dcc-ui-qt-actions) | Click widgets, trigger actions, set values, and drive legacy Qt UI workflows |
| [`dcc-ui-workflow-memory`](https://github.com/dcc-mcp/dcc-ui-workflow-memory) | Remember verified UI selectors, recipes, and failures for later automation |

#### 3D generation and reusable asset sources

| Extension Skill | Capability |
| --- | --- |
| [`dcc-ai-hunyuan3d`](https://github.com/dcc-mcp/dcc-ai-hunyuan3d) | Submit and inspect Tencent Hunyuan text/image-to-3D jobs |
| [`dcc-ai-tripo3d`](https://github.com/dcc-mcp/dcc-ai-tripo3d) | Create, inspect, and download Tripo text/image/multiview 3D tasks |
| [`dcc-asset-polyhaven`](https://github.com/dcc-mcp/dcc-asset-polyhaven) | Browse and download CC0 Poly Haven models, HDRIs, and textures |
| [`dcc-asset-godot-store`](https://github.com/dcc-mcp/dcc-asset-godot-store) | Search and download reusable Godot Asset Store add-ons and projects |
| [`dcc-asset-blender-extensions`](https://github.com/dcc-mcp/dcc-asset-blender-extensions) | Search and download checksum-verified official Blender extensions |
| [`dcc-asset-ambientcg`](https://github.com/dcc-mcp/dcc-asset-ambientcg) | Search and download free ambientCG materials, HDRIs, and models |
| [`dcc-asset-nasa3d`](https://github.com/dcc-mcp/dcc-asset-nasa3d) | Search and download NASA 3D resources with usage notices |
| [`dcc-asset-smithsonian3d`](https://github.com/dcc-mcp/dcc-asset-smithsonian3d) | Search and download Smithsonian Open Access CC0 3D files |
| [`dcc-asset-kenney`](https://github.com/dcc-mcp/dcc-asset-kenney) | Search and download CC0 Kenney game asset packs |
| [`dcc-asset-quaternius`](https://github.com/dcc-mcp/dcc-asset-quaternius) | Search and inspect CC0 Quaternius game asset packs |
| [`dcc-asset-objaverse`](https://github.com/dcc-mcp/dcc-asset-objaverse) | Browse Objaverse metadata and download Creative Commons GLB objects |
| [`dcc-asset-gltf-sample-assets`](https://github.com/dcc-mcp/dcc-asset-gltf-sample-assets) | Download Khronos glTF Sample Assets for testing and validation |
| [`dcc-asset-sketchfab`](https://github.com/dcc-mcp/dcc-asset-sketchfab) | Download eligible Sketchfab models with attribution metadata |
| [`dcc-asset-google-scanned-objects`](https://github.com/dcc-mcp/dcc-asset-google-scanned-objects) | Search and download Google Scanned Objects from Gazebo Fuel |

#### Images, materials, media, geospatial data, and plugins

| Extension Skill | Capability |
| --- | --- |
| [`dcc-ai-openai-image`](https://github.com/dcc-mcp/dcc-ai-openai-image) | Generate and edit texture source images with validated asset descriptors |
| [`dcc-texture-pipeline`](https://github.com/dcc-mcp/dcc-texture-pipeline) | Inspect, color-convert, and optimize textures with OpenImageIO and OpenColorIO |
| [`dcc-materialx`](https://github.com/dcc-mcp/dcc-materialx) | Create, inspect, and validate portable MaterialX documents |
| [`dcc-asset-pexels-video`](https://github.com/dcc-mcp/dcc-asset-free-media) | Search and download Pexels stock video with attribution metadata |
| [`dcc-asset-mixkit-free-media`](https://github.com/dcc-mcp/dcc-asset-free-media) | Download Mixkit video, music, sound effects, and After Effects templates with license metadata |
| [`dcc-asset-game-icons`](https://github.com/dcc-mcp/dcc-asset-free-media) | Search and download CC BY SVG icons for game interfaces |
| [`dcc-asset-google-fonts`](https://github.com/dcc-mcp/dcc-asset-free-media) | Search Google Fonts and download verified fonts with license metadata |
| [`dcc-asset-openstreetmap-city`](https://github.com/dcc-mcp/dcc-asset-geospatial) | Download bounded OpenStreetMap city features as attributed GeoJSON |
| [`dcc-asset-overture-city`](https://github.com/dcc-mcp/dcc-asset-geospatial) | Download bounded Overture Maps city features as licensed GeoJSON |
| [`dcc-plugin-github-releases`](https://github.com/dcc-mcp/dcc-asset-free-media) | Inspect licensed open-source projects and download release plugins with SHA-256 metadata |

#### Pipeline publishing and game delivery

| Extension Skill | Capability |
| --- | --- |
| [`dcc-pipeline-publish`](https://github.com/dcc-mcp/dcc-pipeline-publish) | Create verified manifests connecting DCC exports, OpenUSD, render farms, and ShotGrid/FPT |
| [`dcc-game-release-package`](https://github.com/dcc-mcp/dcc-pipeline-publish) | Package prebuilt Unreal, Unity, and Godot Windows games for installers, SteamPipe, or WeGame |
| [`dcc-game-runtime-acceptance`](https://github.com/dcc-mcp/dcc-pipeline-publish) | Run bounded game-runtime acceptance and preserve hash-bearing evidence |
| [`dcc-game-pv-capture`](https://github.com/dcc-mcp/dcc-pipeline-publish) | Plan and preserve exact-window gameplay shots for HyperFrames PV editing |

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
