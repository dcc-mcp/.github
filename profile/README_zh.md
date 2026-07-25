<p align="center">
  <img src="./dcc-mcp-pipeline-banner.png" alt="DCC-MCP 串联完整的电影与游戏生产流程">
</p>

<p align="center">
  <a href="./README.md">English</a> | 中文
</p>

# DCC MCP

**Skills 驱动，让 Agent 可以可靠操作真实创作工具的公共基础设施。**

DCC-MCP 不做 Agent，也不规定用户必须选择哪个 Agent。我们把不断扩展的桌面 DCC、
游戏引擎、二维工具、生产管理系统、资产提供器、性能分析器和工作室自研宿主接入
同一套发现、执行、安全与运维契约。

## 为什么做这个项目

最直接的 DCC Agent Demo，是让模型临时写一段 `mayapy`、`hython` 或 Blender
Python，然后马上执行。Demo 可以这样做，生产不能靠每次都让模型现场写对脚本。

重复生成代码会持续消耗 Token，结果也会随模型、提示词和上下文变化。每个 adapter
还要重新处理通信、主线程、参数校验、进程生命周期、实例路由和日志。这些公共工程
才是 DCC 集成里最费时间、也最容易踩坑的部分。

DCC-MCP 把它们收进一个可复用框架：

| 层次 | 可以直接复用的能力 |
| --- | --- |
| 接口接入 | MCP/REST endpoint、Host RPC/IPC、类型化 schema、resources、prompts、结构化结果 |
| DCC 运行时 | 主线程亲和、readiness、多实例路由、异步 job、取消、checkpoint、workflow、artefact 交接 |
| Skill 交付 | 有版本的 `SKILL.md` 包、渐进式发现、lint/schema 校验、hot reload、状态持久化、marketplace、项目/团队作用域 |
| 生产运维 | CLI、gateway、Admin UI、权限策略、audit、trace、logs、metrics、health check、回放 |

Agent 会换，模型会升级，但工作室的 DCC 接口、权限边界和 pipeline 经验仍需要长期
维护。框架把这些投入沉淀成可以复用的工程资产。

## MCP 是入口，不是能力上限

我们复用 MCP 这个行业标准接口，不再发明一套只有自己能用的私有协议。但框架并不
局限于 MCP：只要宿主提供稳定的 Python、C++、HTTP、command port 或原生插件接口，
就可以接入同一套控制面。

我们也不会替代厂商已经做好的能力。Unreal Engine 5.8 加入了
[实验性的官方 MCP 和 Toolset Registry](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor)。
我们的
[`unreal-official-mcp` Skill](https://github.com/dcc-mcp/dcc-mcp-unreal/blob/main/src/dcc_mcp_unreal/skills/unreal-official-mcp/SKILL.md)
可以启用并桥接这些官方 toolset，不重新分发 Epic 插件，也不修改官方工具名称和
schema。官方能力、DCC-MCP 自己的能力和工作室内部工具，可以进入同一套 Agent
工作流。

### 没有 API 时：UI Control

让一个新工具增加 AI 接口通常不难。更难的是，工作室里已经使用多年的旧工具没有
API、不能修改源码，或者一部分流程只存在于窗口、弹窗、启动器和 WebView 里，怎么让
Agent 也能调用它们。

dcc-mcp-core 为此提供了类似 Computer Use 的 **UI Control** 能力。它通过 Qt、
原生无障碍接口、WebView 或宿主 UI 后端，执行
`snapshot -> find -> act -> wait -> verify` 的确定性流程。能用原生 Skill/API 时
仍然优先使用；全桌面访问默认拒绝，UI 操作必须有明确作用域，经过策略检查、审计和
结果验证。详细说明见
[UI Control 工作流](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/docs/zh/guide/ui-control-workflows.md)。

## 为什么以 Skill 为生产单元

Skill 不是把脚本换一个目录存放。它把已经验证过的 pipeline 经验，变成有版本、
有 schema、可测试、可分发的工具。

一个成本更低的模型从零编写场景逻辑可能不稳定，但如果它只需要选择一个说明清楚的
工具，再填写经过校验的参数，也能更稳定地完成任务。Skill 可以减少临场代码生成、
Token 消耗和模型差异带来的结果波动。

大型工作室还可以按项目、部门和制作阶段分发不同的 Skill。团队已有的 pipeline
不用推倒重来，只需要逐步封装成 Agent 可以可靠调用的能力。

对 TD/TA 来说，Skill 是把内部需求变成可复用能力的最短路径。宿主连接、主线程执行、
路由、安全和可观测性继续由 Core 与 adapter 负责；项目命名、场景检查、资产准备、
发布卡点、缓存/导出规范和审核交接，则可以直接封装进 `SKILL.md`、`tools.yaml` 和
团队现有脚本。完成的 Skill 可以独立测试、按项目分发，并进入公开或内部 Marketplace，
不需要 fork 控制面，也不需要为每个项目重写 adapter。

## 持续扩展的生态

| 领域 | 项目与 Skills |
| --- | --- |
| 基础设施与分发 | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core)、[`marketplace`](https://github.com/dcc-mcp/marketplace) |
| 桌面 DCC | [Maya](https://github.com/dcc-mcp/dcc-mcp-maya)、[Blender](https://github.com/dcc-mcp/dcc-mcp-blender)、[Houdini](https://github.com/dcc-mcp/dcc-mcp-houdini)、[3ds Max](https://github.com/dcc-mcp/dcc-mcp-3dsmax)、[Nuke](https://github.com/dcc-mcp/dcc-mcp-nuke)、[Katana](https://github.com/dcc-mcp/dcc-mcp-katana)、[MotionBuilder](https://github.com/dcc-mcp/dcc-mcp-mobu)、[ZBrush](https://github.com/dcc-mcp/dcc-mcp-zbrush) |
| 设计与内容工具 | [Photoshop](https://github.com/dcc-mcp/dcc-mcp-photoshop)、[Substance 3D Designer](https://github.com/dcc-mcp/dcc-mcp-substance3d-designer)、[Substance 3D Painter](https://github.com/dcc-mcp/dcc-mcp-substance3d-painter)、[After Effects](https://github.com/dcc-mcp/dcc-mcp-aftereffects)、[Premiere](https://github.com/dcc-mcp/dcc-mcp-premiere)、[GIMP](https://github.com/dcc-mcp/dcc-mcp-gimp)、[Krita](https://github.com/dcc-mcp/dcc-mcp-krita) |
| 游戏与二维引擎 | [Unreal Engine](https://github.com/dcc-mcp/dcc-mcp-unreal)、[Unity](https://github.com/dcc-mcp/dcc-mcp-unity)、[Godot](https://github.com/dcc-mcp/dcc-mcp-godot)、[Tiled](https://github.com/dcc-mcp/dcc-mcp-tiled)、[Material Maker](https://github.com/dcc-mcp/dcc-mcp-material-maker) |
| Pipeline 与质量 | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd)、[Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt)、[MaterialX](https://github.com/dcc-mcp/dcc-materialx)、[纹理 Pipeline](https://github.com/dcc-mcp/dcc-texture-pipeline)、[Pipeline Publish](https://github.com/dcc-mcp/dcc-pipeline-publish)、[RenderDoc](https://github.com/dcc-mcp/dcc-mcp-renderdoc)、[Tracy](https://github.com/dcc-mcp/dcc-mcp-tracy) |
| Marketplace Skills | 资产提供器、2D/3D 生成、UI 自动化、绑定、程序化制作、游戏发行与运行时验收 |

[官方 Marketplace](https://github.com/dcc-mcp/marketplace) 让这些可选能力可以搜索、
安装和升级，也支持工作室维护自己的内部目录。

<!-- markdownlint-disable MD013 -->
[![DCC-MCP Skill Marketplace](https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-core/main/docs/assets/admin-ui/admin-marketplace.png)](https://github.com/dcc-mcp/marketplace)
<!-- markdownlint-enable MD013 -->

## 让 Agent 调用不再是黑盒

Gateway Admin 提供 calls、traces、logs、health、stats 和使用活动。团队可以看到
Agent 选择了什么工具、失败发生在哪一层、哪些 Skill 被频繁调用。发现重复失败后，
可以修改说明、schema 或实现，再用真实调用验证效果，形成工具和 Skill 的迭代闭环。

## 从这里开始

| 需求 | 项目 |
| --- | --- |
| 开发 adapter 或操作在线 DCC | [`dcc-mcp-core`](https://github.com/dcc-mcp/dcc-mcp-core) |
| 发现和分发通用 Skill | [`marketplace`](https://github.com/dcc-mcp/marketplace) |
| 浏览完整生态 | [DCC-MCP 全部仓库](https://github.com/orgs/dcc-mcp/repositories) |
| 接入游戏引擎 | [Unreal Engine](https://github.com/dcc-mcp/dcc-mcp-unreal)、[Unity](https://github.com/dcc-mcp/dcc-mcp-unity)、[Godot](https://github.com/dcc-mcp/dcc-mcp-godot) |
| 建设 Pipeline | [OpenUSD](https://github.com/dcc-mcp/dcc-mcp-openusd)、[Flow Production Tracking](https://github.com/dcc-mcp/dcc-mcp-fpt)、[Texture Pipeline](https://github.com/dcc-mcp/dcc-texture-pipeline) |

更多 adapter、资产提供器、UI 自动化、性能分析和生产 Skill，请浏览
[DCC-MCP 全部仓库](https://github.com/orgs/dcc-mcp/repositories)。

边界也需要说清：Core 不替代各个宿主的 pipeline 语义，也不会在 DCC 没有事务 API
时承诺安全回滚。这些职责仍然属于 adapter 和 pipeline Skill。

如果你也希望 DCC Agent 从 Demo 走向可复用、可部署、可观察的生产工具，欢迎试用并
给项目一个 Star。

## 参与贡献

欢迎提交 Issue 和 Pull Request。Bug、接口缺口和真实生产需求，请反馈到对应仓库。
我们尤其欢迎边界清楚的 adapter、Skill、测试、文档和互操作改进。
