<!-- markdownlint-disable MD013 MD033 MD041 -->

<p align="center">
  <img src="./dcc-mcp-pipeline-banner.png" alt="DCC-MCP 连接电影与游戏制作工具">
</p>

<p align="center">
  <a href="./README.md">English</a> | 中文
</p>

<p align="center">
  <a href="https://dcc-mcp.github.io/zh/">官网</a> ·
  <a href="https://dcc-mcp.github.io/zh/marketplace">技能市场</a> ·
  <a href="https://dcc-mcp.github.io/zh/showcase">案例画廊</a> ·
  <a href="https://dcc-mcp.github.io/zh/agents">Agent 使用指南</a> ·
  <a href="https://dcc-mcp.github.io/zh/ecosystem">生态目录</a>
</p>

# DCC MCP

**让 AI 智能体调用创作工具，完成场景编辑、素材处理和制作流程。**

DCC-MCP 面向美术师、技术美术和工具开发者，将 AI 智能体（Agent）连接到 Maya、
Blender、Houdini 等创作应用。DCC 是 Digital Content Creation（数字内容创作）的
缩写；MCP 是 Model Context Protocol（模型上下文协议），用于连接 AI 应用与外部工具。
Agent 可以按照任务调用这些工具，并检查执行结果。

除了桌面 DCC 应用，DCC-MCP 还连接游戏引擎、二维设计工具、生产管理系统、素材服务、
性能分析工具和工作室自研软件。这些应用都通过统一机制完成应用发现、工具调用、
权限检查和运行状态监控。
DCC-MCP 提供这些连接能力，你可以选择适合自己的 Agent。

## Agent 入口

Skill 是供 Agent 使用的任务指南。操作已接入的应用，从 `dcc-mcp` 开始；开发适配器
或编写 Skill 时，再选择下表中对应的开发指南。安装和配置步骤见
[Agent 使用指南](https://dcc-mcp.github.io/zh/agents)。

| Agent 任务 | 公开 Skill |
| --- | --- |
| 操作正在运行的 DCC 应用、查找工具、安装扩展、排查故障并整理脱敏后的问题报告 | [`@loonghao/dcc-mcp`](https://clawhub.ai/loonghao/skills/dcc-mcp) |
| 开发或改进 DCC-MCP 适配器及其运行环境 | [`@loonghao/dcc-mcp-creator`](https://clawhub.ai/loonghao/skills/dcc-mcp-creator) |
| 为特定 DCC 应用创建、验证或改进 Skill 包 | [`@loonghao/dcc-mcp-skills-creator`](https://clawhub.ai/loonghao/skills/dcc-mcp-skills-creator) |

通常由 `dcc-mcp` Skill 指导 Agent 使用 `dcc-mcp-cli`：先找到正在运行的应用和
可用工具，再阅读工具的参数定义（schema），校验参数后调用，最后检查结果。这些工具
有明确的输入、输出和参数类型，便于 Agent 在调用前了解要求。遇到问题时，Skill 会
指导 Agent 保留调用记录，将脱敏后的报告提交到负责该功能的 Skill、适配器或 Core 仓库。

**Maya MCP**、**3ds Max MCP**、**Blender MCP**、**Unreal MCP**、**Unity MCP**、
**Tuanjie MCP** 和 **Godot MCP** 的使用指南与适配器仓库见下表。
已有 **Maya CLI**、**3ds Max CLI**（`3dsmax` 或 `3ds max`）或 **Blender CLI**
工作流也可以继续使用。DCC-MCP 在应用自身的命令行之外，提供应用发现、工具搜索、
参数检查、调用和结果验证。

| 应用 | 官网使用指南 | 适配器仓库 |
| --- | --- | --- |
| Maya | [用 AI 控制 Maya](https://dcc-mcp.github.io/zh/control/maya) | [`dcc-mcp-maya`](https://github.com/dcc-mcp/dcc-mcp-maya) |
| 3ds Max | [用 AI 控制 3ds Max](https://dcc-mcp.github.io/zh/control/3ds-max) | [`dcc-mcp-3dsmax`](https://github.com/dcc-mcp/dcc-mcp-3dsmax) |
| Blender | [用 AI 控制 Blender](https://dcc-mcp.github.io/zh/control/blender) | [`dcc-mcp-blender`](https://github.com/dcc-mcp/dcc-mcp-blender) |
| Unreal Engine | [用 AI 控制 Unreal Engine](https://dcc-mcp.github.io/zh/control/unreal-engine) | [`dcc-mcp-unreal`](https://github.com/dcc-mcp/dcc-mcp-unreal) |
| Unity | [用 AI 控制 Unity](https://dcc-mcp.github.io/zh/control/unity) | [`dcc-mcp-unity`](https://github.com/dcc-mcp/dcc-mcp-unity) |
| Tuanjie / 团结引擎 | [用 AI 控制团结引擎工作流](https://dcc-mcp.github.io/zh/control/unity) | [`dcc-mcp-unity`](https://github.com/dcc-mcp/dcc-mcp-unity) |
| Godot | [用 AI 控制 Godot](https://dcc-mcp.github.io/zh/control/godot) | [`dcc-mcp-godot`](https://github.com/dcc-mcp/dcc-mcp-godot) |

### 用 Agent 操作游戏引擎

- **Unreal Engine：**检查和编辑关卡、资产、蓝图、过场动画与特效，再通过编辑器内运行
  （PIE）或 Unreal Automation 验证。在支持的编辑器中，也可以调用已安装的 Epic
  工具集；实验性 MCP 插件由 Epic 提供和分发。
- **Unity：**检查项目与场景，执行限定范围且支持撤销的编辑操作，运行测试、录制
  Play Mode 画面，并构建和验证游戏。
- **Tuanjie / 团结引擎：**先检查可选的原生 Codely `CustomTool` 目录，再使用其中的
  图像、精灵图、3D、材质、音频、视频或地形生成工具。登录、积分、下载和任务恢复由
  团结引擎的相关软件包处理；DCC-MCP 负责查找、调用这些工具并检查结果。
- **Godot：**检查和编辑项目与场景，调用编辑器和游戏运行时工具，并通过 Godot
  适配器验证 2D 或 3D 结果。

## 为什么做这个项目

让模型编写并运行 `mayapy`、`hython` 或 Blender Python 脚本，可以快速演示一个
DCC 任务。用于日常制作时，还需要管理权限、校验参数、记录过程，并确认结果符合要求。

如果每次都临时生成代码，就需要反复检查代码是否适合当前场景。适配器开发者也常常
重复实现通信、主线程调度、进程管理、多实例选择和日志等功能。

DCC-MCP 将这些通用功能集中到一个可复用的框架中：

| 层次 | 可以直接复用的能力 |
| --- | --- |
| 接口接入 | MCP 和 REST 接口、应用内 RPC/进程间通信、参数类型定义、资源、提示词和结构化结果 |
| 应用运行 | 主线程调度、就绪检查、多实例路由、异步任务、取消、检查点、工作流和产物交接 |
| Skill 管理 | 版本管理、按需发现、格式与参数定义校验、热重载、状态保存、市场分发，以及项目和团队范围设置 |
| 运行维护 | 命令行、网关、管理界面、权限策略、审计、调用追踪、日志、指标、健康检查和回放 |

团队可以继续维护已有的 DCC 接口、权限规则和制作流程，在更换 Agent 或模型时复用
这些工具。

## 通过 MCP 和应用原生接口接入

DCC-MCP 使用 MCP 连接 Agent，也支持通过 Python、C++、HTTP、命令端口或原生插件
连接创作应用。应用提供的稳定接口可以纳入同一套发现、调用和管理流程。

厂商提供的工具也可以接入。Unreal Engine 5.8 加入了
[实验性的官方 MCP 和 Toolset Registry](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor)。
我们的
[`unreal-official-mcp` Skill](https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/src/dcc_mcp_unreal/skills/unreal-official-mcp/SKILL.md)
可以启用并连接这些官方工具集，保留原有工具名称和参数定义。插件仍由 Epic 分发。
Agent 可以在同一工作流中使用厂商工具、DCC-MCP 工具和工作室内部工具。

Unity 项目也可以用同样的方式复用团结引擎的可选 AI 软件包。
[`unity-tuanjie-ai` Skill](https://github.com/dcc-mcp/dcc-mcp-unity/blob/main/src/dcc_mcp_unity/skills/unity-tuanjie-ai/SKILL.md)
先检查原生 Codely `CustomTool` 目录，并且只执行本次检查返回的工具。登录、积分、下载
和任务恢复由团结引擎的相关软件包处理；DCC-MCP 负责工具发现、调用和结果验证。

### 没有 API 时：UI Control

一些旧工具没有 API，也无法修改源码；还有些操作只能在窗口、弹窗或内嵌网页中完成。
dcc-mcp-core 的 **UI Control** 让 Agent 通过 Qt、系统无障碍接口、WebView 或应用
提供的界面接口完成这些操作。界面操作统一通过项目的
[DCC-CUA](https://github.com/dcc-mcp/dcc-cua) 与 UI Control 路由执行。
流程是“查看界面 → 定位控件 → 操作 → 等待 → 验证”
（`snapshot -> find -> act -> wait -> verify`）。

有原生 Skill 或 API 时优先使用。界面操作须限定范围、检查权限、保留审计记录并验证
结果；默认不允许访问整个桌面。详细说明见
[UI Control 工作流](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/zh/guide/ui-control-workflows.md)。

## 用 Skill 复用团队的制作经验

Skill 可以将任务指南、工具定义和现有脚本组合起来，把团队验证过的制作流程交给 Agent
使用。每个 Skill 可以独立管理版本、测试和分发。

有了明确的工具说明和参数定义，Agent 可以复用现有操作，减少为相同任务反复编写代码。
参数校验和执行后检查仍然必要；实际效果取决于工具实现、模型和任务。大型工作室可以
按项目、部门或制作阶段分发不同的 Skill。

技术总监（TD）和技术美术（TA）可以将项目命名规则、场景检查、资产准备、发布前检查、
缓存与导出规范、审核交接等流程写入 `SKILL.md`、`tools.yaml` 和现有脚本。
Core 与适配器负责连接应用、调度主线程、调用路由、权限控制和运行记录。团队可以通过
公开或内部 Marketplace 分发 Skill，复用同一套基础设施和适配器。

## 持续扩展的生态

| 领域 | 项目与 Skills |
| --- | --- |
| 基础设施与分发 | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core)、[`marketplace`](https://github.com/dcc-mcp/marketplace) |
| 桌面 DCC | [Maya MCP](https://github.com/dcc-mcp/dcc-mcp-maya)、[Blender MCP](https://github.com/dcc-mcp/dcc-mcp-blender)、[Houdini](https://github.com/dcc-mcp/dcc-mcp-houdini)、[3ds Max MCP](https://github.com/dcc-mcp/dcc-mcp-3dsmax)、[Marmoset Toolbag](https://github.com/dcc-mcp/dcc-mcp-marmoset)、[Nuke](https://github.com/dcc-mcp/dcc-mcp-nuke)、[Katana](https://github.com/dcc-mcp/dcc-mcp-katana)、[MotionBuilder](https://github.com/dcc-mcp/dcc-mcp-mobu)、[ZBrush](https://github.com/dcc-mcp/dcc-mcp-zbrush) |
| 设计与内容工具 | [Photoshop](https://github.com/dcc-mcp/dcc-mcp-photoshop)、[Substance 3D Designer](https://github.com/dcc-mcp/dcc-mcp-substance3d-designer)、[Substance 3D Painter](https://github.com/dcc-mcp/dcc-mcp-substance3d-painter)、[After Effects](https://github.com/dcc-mcp/dcc-mcp-aftereffects)、[Premiere](https://github.com/dcc-mcp/dcc-mcp-premiere)、[GIMP](https://github.com/dcc-mcp/dcc-mcp-gimp)、[Krita](https://github.com/dcc-mcp/dcc-mcp-krita) |
| 游戏与二维引擎 | [Unreal Engine 官方 MCP 桥接](https://github.com/dcc-mcp/dcc-mcp-unreal)、[Unity 与团结 AI](https://github.com/dcc-mcp/dcc-mcp-unity)、[Godot](https://github.com/dcc-mcp/dcc-mcp-godot)、[Tiled](https://github.com/dcc-mcp/dcc-mcp-tiled)、[Material Maker](https://github.com/dcc-mcp/dcc-mcp-material-maker) |
| 制作流程与质量检查 | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd)、[Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt)、[MaterialX](https://github.com/dcc-mcp/dcc-materialx)、[纹理处理](https://github.com/dcc-mcp/dcc-texture-pipeline)、[制作流程发布](https://github.com/dcc-mcp/dcc-pipeline-publish)、[RenderDoc](https://github.com/dcc-mcp/dcc-mcp-renderdoc)、[Tracy](https://github.com/dcc-mcp/dcc-mcp-tracy) |
| 扩展 Skill | 素材服务、2D/3D 生成、界面自动化、角色绑定、程序化制作、游戏发行与运行验收 |

[官方技能市场](https://dcc-mcp.github.io/zh/marketplace)支持搜索、安装和升级扩展，
工作室也可以维护内部目录。你还可以浏览
[作品案例与示例提示词](https://dcc-mcp.github.io/zh/showcase)，或查看
[目录源码](https://github.com/dcc-mcp/marketplace)。

### 扩展 Skill 目录

以下扩展可在[官方目录](https://github.com/dcc-mcp/marketplace/blob/main/marketplace.json)
中查找。安装前，Agent 应先搜索最新目录，确认可用的软件包：

```bash
dcc-mcp-cli marketplace search --query "<capability>" --limit 20
dcc-mcp-cli marketplace install <package_name> --dcc <dcc_name>
```

#### 角色绑定、程序化制作与界面自动化

| 扩展 Skill | 能力 |
| --- | --- |
| [`dcc-mcp-maya-mgear`](https://github.com/dcc-mcp/dcc-mcp-maya-mgear) | 在 Maya 中检查、构建和管理 mGear Shifter 角色绑定 |
| [`dcc-mcp-maya-advancedskeleton`](https://github.com/dcc-mcp/dcc-mcp-maya-advancedskeleton) | 检查模板，创建、导入、构建或重建 AdvancedSkeleton 角色绑定 |
| [`dcc-mcp-maya-procedural-architecture`](https://github.com/dcc-mcp/dcc-mcp-maya-procedural-architecture) | 在 Maya 中按种子生成房屋，配备 Arnold 材质，可选用 CC0 HDR 环境光 |
| [`dcc-ui-qt-inspector`](https://github.com/dcc-mcp/dcc-ui-qt-inspector) | 在使用 PySide/PyQt 的 DCC 应用中查找 Qt 窗口、控件及其定位信息 |
| [`dcc-ui-qt-actions`](https://github.com/dcc-mcp/dcc-ui-qt-actions) | 点击控件、触发操作和设置数值，自动执行已有 Qt 界面流程 |
| [`dcc-ui-workflow-memory`](https://github.com/dcc-mcp/dcc-ui-workflow-memory) | 保存验证过的控件定位信息、操作步骤和失败记录 |

#### 3D 生成与素材服务

| 扩展 Skill | 能力 |
| --- | --- |
| [`dcc-ai-hunyuan3d`](https://github.com/dcc-mcp/dcc-ai-hunyuan3d) | 提交和查询腾讯混元 3D 生成任务，支持文字或图片输入 |
| [`dcc-ai-tripo3d`](https://github.com/dcc-mcp/dcc-ai-tripo3d) | 使用文字、图片或多视图创建 Tripo 3D 生成任务，查询进度并下载结果 |
| [`dcc-asset-polyhaven`](https://github.com/dcc-mcp/dcc-asset-polyhaven) | 浏览和下载 CC0 Poly Haven 模型、HDRI 与纹理 |
| [`dcc-asset-godot-store`](https://github.com/dcc-mcp/dcc-asset-godot-store) | 搜索和下载可复用的 Godot Asset Store 插件与项目 |
| [`dcc-asset-blender-extensions`](https://github.com/dcc-mcp/dcc-asset-blender-extensions) | 搜索和下载官方 Blender 扩展，并校验文件完整性 |
| [`dcc-asset-ambientcg`](https://github.com/dcc-mcp/dcc-asset-ambientcg) | 搜索和下载免费 ambientCG 材质、HDRI 与模型 |
| [`dcc-asset-nasa3d`](https://github.com/dcc-mcp/dcc-asset-nasa3d) | 搜索和下载带使用声明的 NASA 3D 资源 |
| [`dcc-asset-smithsonian3d`](https://github.com/dcc-mcp/dcc-asset-smithsonian3d) | 搜索和下载 Smithsonian Open Access CC0 3D 文件 |
| [`dcc-asset-kenney`](https://github.com/dcc-mcp/dcc-asset-kenney) | 搜索和下载 CC0 Kenney 游戏资产包 |
| [`dcc-asset-quaternius`](https://github.com/dcc-mcp/dcc-asset-quaternius) | 搜索和检查 CC0 Quaternius 游戏资产包 |
| [`dcc-asset-objaverse`](https://github.com/dcc-mcp/dcc-asset-objaverse) | 浏览 Objaverse 资源信息，下载采用 Creative Commons 许可的 GLB 模型 |
| [`dcc-asset-gltf-sample-assets`](https://github.com/dcc-mcp/dcc-asset-gltf-sample-assets) | 下载用于测试与验证的 Khronos glTF Sample Assets |
| [`dcc-asset-sketchfab`](https://github.com/dcc-mcp/dcc-asset-sketchfab) | 下载开放下载的 Sketchfab 模型，并保留署名信息 |
| [`dcc-asset-google-scanned-objects`](https://github.com/dcc-mcp/dcc-asset-google-scanned-objects) | 从 Gazebo Fuel 搜索和下载 Google Scanned Objects |

#### 图像、材质、媒体、地理数据与插件

| 扩展 Skill | 能力 |
| --- | --- |
| [`dcc-ai-openai-image`](https://github.com/dcc-mcp/dcc-ai-openai-image) | 生成和编辑纹理源图，并返回经过验证的资产描述 |
| [`dcc-texture-pipeline`](https://github.com/dcc-mcp/dcc-texture-pipeline) | 使用 OpenImageIO 和 OpenColorIO 检查、转换与优化纹理 |
| [`dcc-materialx`](https://github.com/dcc-mcp/dcc-materialx) | 创建、检查和验证可移植的 MaterialX 文档 |
| [`dcc-asset-pexels-video`](https://github.com/dcc-mcp/dcc-asset-free-media) | 搜索和下载 Pexels 视频，并保留署名信息 |
| [`dcc-asset-mixkit-free-media`](https://github.com/dcc-mcp/dcc-asset-free-media) | 下载 Mixkit 视频、音乐、音效和 After Effects 模板，并保留许可信息 |
| [`dcc-asset-game-icons`](https://github.com/dcc-mcp/dcc-asset-free-media) | 搜索和下载用于游戏界面的 CC BY SVG 图标 |
| [`dcc-asset-google-fonts`](https://github.com/dcc-mcp/dcc-asset-free-media) | 搜索 Google Fonts，下载并验证字体，保留许可信息 |
| [`dcc-asset-openstreetmap-city`](https://github.com/dcc-mcp/dcc-asset-geospatial) | 下载指定范围内的 OpenStreetMap 城市数据，输出带署名信息的 GeoJSON |
| [`dcc-asset-overture-city`](https://github.com/dcc-mcp/dcc-asset-geospatial) | 下载指定范围内的 Overture Maps 城市数据，输出带许可信息的 GeoJSON |
| [`dcc-plugin-github-releases`](https://github.com/dcc-mcp/dcc-asset-free-media) | 检查开源项目许可，下载已发布的插件，并记录 SHA-256 校验值 |

#### 制作流程发布与游戏交付

| 扩展 Skill | 能力 |
| --- | --- |
| [`dcc-pipeline-publish`](https://github.com/dcc-mcp/dcc-pipeline-publish) | 创建并验证发布清单，关联 DCC 导出、OpenUSD、渲染农场与 ShotGrid/FPT |
| [`dcc-game-release-package`](https://github.com/dcc-mcp/dcc-pipeline-publish) | 将已构建的 Unreal、Unity、Godot Windows 游戏制作成安装包，或打包为 SteamPipe、WeGame 所需文件 |
| [`dcc-game-runtime-acceptance`](https://github.com/dcc-mcp/dcc-pipeline-publish) | 在限定范围内运行游戏验收，保存结果和文件哈希 |
| [`dcc-game-pv-capture`](https://github.com/dcc-mcp/dcc-pipeline-publish) | 规划并录制指定游戏窗口的画面，供 HyperFrames 剪辑宣传片使用 |

<!-- markdownlint-disable MD013 -->
[![DCC-MCP Skill Marketplace](https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-core/main/docs/assets/admin-ui/admin-marketplace.png)](https://dcc-mcp.github.io/zh/marketplace)
<!-- markdownlint-enable MD013 -->

## 查看 Agent 的调用过程

网关管理界面提供工具调用、调用追踪、日志、健康状态和使用统计。团队可以查看 Agent
选择了什么工具、调用在哪一步失败，以及哪些 Skill 最常用。根据这些记录修改工具说明、
参数定义或实现后，再通过实际调用检查改进效果。

## 从这里开始

| 需求 | 项目 |
| --- | --- |
| 了解项目或配置 Agent | [官网](https://dcc-mcp.github.io/zh/)、[Agent 使用指南](https://dcc-mcp.github.io/zh/agents)、[案例画廊](https://dcc-mcp.github.io/zh/showcase) |
| 开发适配器或了解公共运行框架 | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core) |
| 发现和分发通用 Skill | [`marketplace`](https://github.com/dcc-mcp/marketplace) |
| 浏览完整生态 | [DCC-MCP 全部仓库](https://github.com/orgs/dcc-mcp/repositories) |
| 接入游戏引擎 | [Unreal Engine 官方 MCP 桥接](https://github.com/dcc-mcp/dcc-mcp-unreal)、[Unity 与团结 AI](https://github.com/dcc-mcp/dcc-mcp-unity)、[Godot](https://github.com/dcc-mcp/dcc-mcp-godot) |
| 集成制作流程 | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd)、[Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt)、[纹理处理](https://github.com/dcc-mcp/dcc-texture-pipeline) |

更多适配器、素材服务、界面自动化、性能分析工具和制作流程 Skill，请浏览
[DCC-MCP 全部仓库](https://github.com/orgs/dcc-mcp/repositories)。

Core 提供共用的连接和运行机制，各应用的制作规则由适配器和 Skill 实现。如果应用没有
事务 API，Core 无法保证操作能安全回滚。

欢迎在自己的制作流程中试用 DCC-MCP。如果项目对你有帮助，可以用 Star 支持我们。

## 参与贡献

欢迎在相关仓库提交 Issue 和 Pull Request，反馈问题、缺少的接口和制作需求。
适配器、Skill、测试、文档，以及工具间协作的改进都欢迎参与。
