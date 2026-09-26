<!-- markdownlint-disable MD013 MD033 MD041 -->

<p align="center">
  <img src="./dcc-mcp-pipeline-banner.png" alt="DCC-MCP connects film and game production tools">
</p>

<p align="center">
  English | <a href="./README_zh.md">中文</a>
</p>

<p align="center">
  <a href="https://dcc-mcp.github.io/">Website</a> ·
  <a href="https://dcc-mcp.github.io/marketplace">Marketplace</a> ·
  <a href="https://dcc-mcp.github.io/showcase">Showcase</a> ·
  <a href="https://dcc-mcp.github.io/agents">For Agents</a> ·
  <a href="https://dcc-mcp.github.io/ecosystem">Ecosystem</a>
</p>

# DCC MCP

**Connect AI agents to creative tools for scene editing, asset processing, and production workflows.**

DCC-MCP helps artists, technical artists, and tool developers connect AI agents
to applications such as Maya, Blender, and Houdini. DCC stands for Digital
Content Creation; MCP stands for Model Context Protocol, an interface between
AI applications and external tools. An agent can call these tools to carry out
a task and check the results.

Alongside desktop DCC applications, DCC-MCP connects game engines, 2D design
tools, production systems, asset services, profilers, and custom studio software.
They share application discovery, tool calls, permission checks, and monitoring.
DCC-MCP provides the connections; you choose the agent.

## Agent entry points

A Skill is a task guide for agents. Start with `dcc-mcp` to operate an integrated
application, or choose a creator Skill below to develop adapters or Skill
packages. See the [agent guide](https://dcc-mcp.github.io/agents) for installation
and configuration.

| Agent task | Public Skill |
| --- | --- |
| Operate running DCC applications, find tools, install extensions, diagnose failures, and prepare sanitized bug reports | [`@loonghao/dcc-mcp`](https://clawhub.ai/loonghao/skills/dcc-mcp) |
| Build or improve a DCC-MCP adapter and runtime | [`@loonghao/dcc-mcp-creator`](https://clawhub.ai/loonghao/skills/dcc-mcp-creator) |
| Create, validate, or improve a DCC-specific Skill package | [`@loonghao/dcc-mcp-skills-creator`](https://clawhub.ai/loonghao/skills/dcc-mcp-skills-creator) |

The `dcc-mcp` Skill guides agents through `dcc-mcp-cli`: find a running
application and its available tools, read the selected tool's parameter
definition (schema), validate the arguments, call the tool, and check the result.
These typed tools define their inputs, outputs, and argument types so agents
can inspect requirements before calling them. When a call fails, the Skill
guides agents to preserve traces and submit a sanitized report to the responsible
Skill, adapter, or Core repository.

Find guides and adapters for **Maya MCP**, **3ds Max MCP**, **Blender MCP**,
**Unreal MCP**, **Unity MCP**, **Tuanjie MCP**, and **Godot MCP** below.
Existing **Maya CLI**, **3ds Max CLI** (`3dsmax` or `3ds max`), and **Blender CLI**
workflows can continue to use each application's command line. DCC-MCP adds
application discovery, tool search, parameter inspection, calls, and result
verification.

| Application | Website guide | Adapter repository |
| --- | --- | --- |
| Maya | [Control Maya with AI](https://dcc-mcp.github.io/control/maya) | [`dcc-mcp-maya`](https://github.com/dcc-mcp/dcc-mcp-maya) |
| 3ds Max | [Control 3ds Max with AI](https://dcc-mcp.github.io/control/3ds-max) | [`dcc-mcp-3dsmax`](https://github.com/dcc-mcp/dcc-mcp-3dsmax) |
| Blender | [Control Blender with AI](https://dcc-mcp.github.io/control/blender) | [`dcc-mcp-blender`](https://github.com/dcc-mcp/dcc-mcp-blender) |
| Unreal Engine | [Control Unreal Engine with AI](https://dcc-mcp.github.io/control/unreal-engine) | [`dcc-mcp-unreal`](https://github.com/dcc-mcp/dcc-mcp-unreal) |
| Unity | [Control Unity with AI](https://dcc-mcp.github.io/control/unity) | [`dcc-mcp-unity`](https://github.com/dcc-mcp/dcc-mcp-unity) |
| Tuanjie / 团结引擎 | [Control Tuanjie workflows with AI](https://dcc-mcp.github.io/control/unity) | [`dcc-mcp-unity`](https://github.com/dcc-mcp/dcc-mcp-unity) |
| Godot | [Control Godot with AI](https://dcc-mcp.github.io/control/godot) | [`dcc-mcp-godot`](https://github.com/dcc-mcp/dcc-mcp-godot) |

### Game-engine agent workflows

- **Unreal Engine:** inspect and author levels, assets, Blueprints, cinematics,
  and effects, then validate through PIE or Unreal Automation. On supported
  editors, the adapter can bridge installed Epic toolsets while Epic continues
  to own and distribute its experimental MCP plugin.
- **Unity:** inspect project and scene state, make bounded Undo-backed editor
  changes, run tests, capture Play Mode, and produce verified builds through
  the Unity adapter's typed tools.
- **Tuanjie / 团结引擎:** inspect the optional native Codely `CustomTool`
  catalog before using its image, sprite, 3D, material, audio, video, or terrain
  generators. Tuanjie continues to own sign-in, credits, downloads, and task
  recovery; DCC-MCP owns the surrounding discovery, routing, and verification.
- **Godot:** inspect and edit projects and scenes, exercise editor and game
  runtime tools, and validate 2D or 3D results through the Godot adapter.

## Why this project exists

A model can write and run a `mayapy`, `hython`, or Blender Python script to
demonstrate a DCC task. Everyday production also needs permission controls,
parameter checks, execution records, and verification of the results.

Generating fresh code for each task means reviewing whether it fits the current
scene. Adapter authors also repeat work on transport, main-thread dispatch,
process management, instance selection, and logging.

DCC-MCP brings those shared functions into a reusable framework:

| Layer | Shared capability |
| --- | --- |
| Integration | MCP and REST endpoints, Host RPC/IPC, typed schemas, resources, prompts, and structured results |
| DCC runtime | Main-thread dispatch, readiness checks, multi-instance routing, async jobs, cancellation, checkpoints, workflows, and artefact hand-off |
| Skill delivery | Versioned `SKILL.md` packages, progressive discovery, lint/schema validation, hot reload, persistence, marketplace distribution, and project/team scopes |
| Operations | CLI, gateway, Admin UI, policies, audit records, traces, logs, metrics, health checks, and replay |

Teams can maintain their existing DCC interfaces, permission rules, and
production workflows, then reuse those tools when changing agents or models.

## Connect through MCP and application APIs

DCC-MCP uses MCP to connect agents and can connect creative applications through
Python, C++, HTTP, command ports, or native plugins. Stable application APIs can
join the same discovery, execution, and management workflow.

Vendor tools can join that workflow too. Unreal Engine 5.8 introduced an
[experimental official MCP server and Toolset Registry](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor).
Our
[`unreal-official-mcp` Skill](https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/src/dcc_mcp_unreal/skills/unreal-official-mcp/SKILL.md)
enables and bridges those official toolsets without redistributing Epic's
plugin or changing its tool names and schemas. Vendor tools, DCC-MCP tools, and
studio tools can share one agent-facing workflow.

Unity projects can use the same pattern with Tuanjie Editor's optional AI
packages. The
[`unity-tuanjie-ai` Skill](https://github.com/dcc-mcp/dcc-mcp-unity/blob/main/src/dcc_mcp_unity/skills/unity-tuanjie-ai/SKILL.md)
inspects the native Codely `CustomTool` catalog and only executes a tool from a
fresh inspection result. Tuanjie's packages continue to own sign-in, credits,
downloads, and task recovery; DCC-MCP provides the typed discovery, routing,
and verification workflow around those vendor capabilities.

### When there is no API: UI Control

Some older tools have no API and cannot be modified. Other operations are only
available through windows, dialogs, or embedded web pages. dcc-mcp-core provides
**UI Control** for these tasks through Qt, native accessibility, webviews, or
application-specific UI backends. UI actions use the project's
[DCC-CUA](https://github.com/dcc-mcp/dcc-cua) and UI Control routing. The workflow follows a
`snapshot -> find -> act -> wait -> verify` loop.

Native Skills and APIs remain preferred. UI actions must stay scoped,
policy-checked, audited, and verified; whole-desktop access is denied by default.
See the
[UI Control workflow guide](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/guide/ui-control-workflows.md).

## Reuse production knowledge with Skills

A Skill can combine task instructions, tool definitions, and existing scripts
to make a team's tested production workflows available to agents. Each Skill
can be versioned, tested, and distributed independently.

Clear tool descriptions and parameter definitions let agents reuse operations
instead of generating code repeatedly for the same task. Parameter validation
and result checks remain necessary; outcomes depend on the tool, model, and
task. Large studios can distribute different Skills by project, department,
or production stage.

Technical directors (TDs) and technical artists (TAs) can package naming rules,
scene checks, asset preparation, pre-publish checks, cache/export rules, and
review hand-offs in `SKILL.md`, `tools.yaml`, and existing studio scripts.
Core and the adapter handle connectivity, main-thread execution, routing,
permissions, and execution records. Teams can distribute Skills through a public
or private Marketplace while reusing the same infrastructure and adapters.

## A growing ecosystem

| Area | Projects and Skills |
| --- | --- |
| Foundation and distribution | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core), [`marketplace`](https://github.com/dcc-mcp/marketplace) |
| Desktop DCCs | [Maya MCP](https://github.com/dcc-mcp/dcc-mcp-maya), [Blender MCP](https://github.com/dcc-mcp/dcc-mcp-blender), [Houdini](https://github.com/dcc-mcp/dcc-mcp-houdini), [3ds Max MCP](https://github.com/dcc-mcp/dcc-mcp-3dsmax), [Marmoset Toolbag](https://github.com/dcc-mcp/dcc-mcp-marmoset), [Nuke](https://github.com/dcc-mcp/dcc-mcp-nuke), [Katana](https://github.com/dcc-mcp/dcc-mcp-katana), [MotionBuilder](https://github.com/dcc-mcp/dcc-mcp-mobu), [ZBrush](https://github.com/dcc-mcp/dcc-mcp-zbrush) |
| Design and content tools | [Photoshop](https://github.com/dcc-mcp/dcc-mcp-photoshop), [Substance 3D Designer](https://github.com/dcc-mcp/dcc-mcp-substance3d-designer), [Substance 3D Painter](https://github.com/dcc-mcp/dcc-mcp-substance3d-painter), [After Effects](https://github.com/dcc-mcp/dcc-mcp-aftereffects), [Premiere](https://github.com/dcc-mcp/dcc-mcp-premiere), [GIMP](https://github.com/dcc-mcp/dcc-mcp-gimp), [Krita](https://github.com/dcc-mcp/dcc-mcp-krita) |
| Game and 2D engines | [Unreal Engine official MCP bridge](https://github.com/dcc-mcp/dcc-mcp-unreal), [Unity and Tuanjie AI](https://github.com/dcc-mcp/dcc-mcp-unity), [Godot](https://github.com/dcc-mcp/dcc-mcp-godot), [Tiled](https://github.com/dcc-mcp/dcc-mcp-tiled), [Material Maker](https://github.com/dcc-mcp/dcc-mcp-material-maker) |
| Pipeline and quality | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd), [Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt), [MaterialX](https://github.com/dcc-mcp/dcc-materialx), [Texture Pipeline](https://github.com/dcc-mcp/dcc-texture-pipeline), [Pipeline Publish](https://github.com/dcc-mcp/dcc-pipeline-publish), [RenderDoc](https://github.com/dcc-mcp/dcc-mcp-renderdoc), [Tracy](https://github.com/dcc-mcp/dcc-mcp-tracy) |
| Extension Skills | Asset services, 2D/3D generation, UI automation, rigging, procedural authoring, game delivery, and runtime acceptance |

The [official Marketplace](https://dcc-mcp.github.io/marketplace) makes those
optional capabilities searchable, installable, upgradeable, and suitable for
private studio catalogs too. Browse [real outputs and reusable prompts](https://dcc-mcp.github.io/showcase),
or inspect the [catalog source](https://github.com/dcc-mcp/marketplace).

### Extension Skill catalog

Find the extensions below in the
[official catalog](https://github.com/dcc-mcp/marketplace/blob/main/marketplace.json).
Agents should search the latest catalog to confirm package availability before
installation:

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
[![DCC-MCP Skill Marketplace](https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-core/main/docs/assets/admin-ui/admin-marketplace.png)](https://dcc-mcp.github.io/marketplace)
<!-- markdownlint-enable MD013 -->

## Inspect agent tool calls

The Gateway Admin UI exposes calls, traces, logs, health, statistics, and usage
activity. Teams can see which tools agents selected, where calls failed, and
which Skills are used most often. Use those records to improve a description,
parameter definition, or implementation, then check the changes through real
calls.

## Start here

| Need | Project |
| --- | --- |
| Learn about the project or configure an agent | [Website](https://dcc-mcp.github.io/), [For Agents](https://dcc-mcp.github.io/agents), [Showcase](https://dcc-mcp.github.io/showcase) |
| Build an adapter or explore the shared runtime | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core) |
| Discover and distribute reusable Skills | [`marketplace`](https://github.com/dcc-mcp/marketplace) |
| Explore the full ecosystem | [All DCC-MCP repositories](https://github.com/orgs/dcc-mcp/repositories) |
| Integrate game engines | [Unreal Engine official MCP bridge](https://github.com/dcc-mcp/dcc-mcp-unreal), [Unity and Tuanjie AI](https://github.com/dcc-mcp/dcc-mcp-unity), [Godot](https://github.com/dcc-mcp/dcc-mcp-godot) |
| Build pipeline integrations | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd), [Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt), [Texture Pipeline](https://github.com/dcc-mcp/dcc-texture-pipeline) |

Browse the [DCC-MCP repositories](https://github.com/orgs/dcc-mcp/repositories)
for more adapters, asset services, UI automation, profilers, and production
Skills.

Core provides shared connectivity and runtime services. Adapters and Skills
implement each application's production rules. If an application has no
transaction API, Core cannot guarantee safe rollback.

Try DCC-MCP in your own production workflows. If it helps, support the project
with a Star.

## Contributing

Issues and pull requests are welcome. Please report bugs, integration gaps, and
production workflow needs in the relevant repository. Focused adapters, Skills,
tests, documentation, and interoperability improvements are especially useful.
