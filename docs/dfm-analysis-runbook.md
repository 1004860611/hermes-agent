---
title: "单次 DFM 分析数据说明"
status: active
milestone: M2.5
last_updated: 2026-07-21
type: living-runbook
owners: DFM 工程团队
---

# 单次 DFM 分析数据说明

本文说明当前 M2.5 开发版本中，一次真实 DFM 分析如何执行、输入和过程数据保存在哪里、结果文件分别有什么用途，以及出现异常时应检查哪些文件。

本文是随 DFM 里程碑持续更新的活文档。这里描述的是**当前已实现行为**；长期目标、尚未实现的输入模式和演进路线参见 [DFM Hermes Agent 开发目标与路线图](plans/2026-07-13-dfm-hermes-agent-development-roadmap.md)。

## 1. M1.2 适用范围

| 能力 | M1 状态 |
| --- | --- |
| 制造工艺 | 注塑 `injection` 完整基线；压铸 `die_casting` 首条 STEP 拓扑有效性门 |
| 三维输入 | 支持 STEP/STP；Parasolid `x_t` 可登记，配置 `dfm.nx.endpoint` 后通过远程 NX HTTP Backend 查询/执行，未配置时返回 `dependency_missing` |
| 2D 图纸/OCR | 接口预留，尚未形成生产分析闭环 |
| 混合输入融合 | 接口预留，尚未形成生产分析闭环 |
| 几何计算 | OpenCascade / `pythonocc-core` |
| 工艺规则 | 注塑 `injection.legacy-baseline@1.1.0`；压铸 `die_casting.topology-baseline@1.0.0` |
| 执行方式 | Hermes 主进程管理 Run，STEP worker 隔离子进程执行 |
| 结果 | Measurement/Evaluation JSON、兼容报告 JSON、Markdown、PPTX、PNG 证据、高亮 STEP |
| Desktop | 复用附件上传、聊天进度和 Artifacts 展示 |

M2.5 不分析模具设计模型，也不分析型芯、型腔、滑块、顶针、浇注系统或冷却系统；压铸尚未开放壁厚、拔模和倒扣规则。

## 2. 一次分析的调用流程

```text
用户 / Desktop
  │
  ├─ 上传 STEP（或登记 x_t）
  │
  v
Hermes Agent
  │  理解目标、选择 injection/die_casting、必要时追问
  │
  ├─ dfm_project(create)
  ├─ dfm_project(add_input)
  ├─ dfm_project(confirm_fact)      # 可选
  ├─ dfm_analysis(plan)
  ├─ dfm_analysis(start)
  ├─ dfm_analysis(status)           # 轮询/进度
  └─ dfm_analysis(result)
          │
          v
DFMService → JobManager → ProcessAdapter + Analyzer → geometry worker
                                      │
                                      ├─ OpenCascade 几何计算
                                      ├─ 注塑规则检查
                                      └─ 压铸拓扑门（当前）
                                      ├─ 证据图片渲染
                                      └─ JSON/MD/PPTX 报告生成
```

### 2.1 Agent 与确定性计划的分工

- Hermes Agent 负责理解用户意图、选择工艺、补充或确认工程事实，并决定何时调用 DFM 工具。
- `DFMService` 不直接执行模型临时生成的几何步骤。它调用 ProcessAdapter，根据已确认事实、工艺默认值和版本化分析范围编译结构化 Plan。
- Run 启动前会保存 Plan 快照；worker 只执行该快照对应的参数和操作。
- OpenCascade 测量值和规则判断由确定性代码产生，不由大模型编造。

## 3. 数据根目录与标识

DFM 工作区跟随当前 Hermes profile：

```text
<HERMES_HOME>/workspace/dfm/
```

Windows 默认 profile 通常为：

```text
C:\Users\<用户名>\.hermes\workspace\dfm\
```

Docker 中通常通过 `HERMES_HOME` 指向持久卷，例如：

```text
/data/hermes/workspace/dfm/
```

一次分析涉及三个主要标识：

| 标识 | 示例 | 作用 |
| --- | --- | --- |
| `project_id` | `dfm_bcd8dc5bac814f30` | 一个可持续追加输入、事实、Plan 和 Run 的 DFM 项目 |
| `plan_id` | `plan_4c61...` | 一份已持久化的分析计划 |
| `run_id` | `run_28d9bfd0564e4f1e` | 对某个 Plan 的一次实际执行 |

同一项目可以有多个 Plan 和多个 Run。诊断时必须同时确认 `project_id` 与 `run_id`，不能只看聊天会话 ID。

## 4. 当前真实目录结构

```text
<HERMES_HOME>/workspace/dfm/
├── projects/
│   └── <project_id>/
│       ├── project_manifest.json
│       ├── inputs/
│       │   └── input_<sha256前16位>.stp
│       ├── runs/
│       │   └── <run_id>/
│       │       ├── request.json
│       │       ├── events.jsonl
│       │       ├── worker.stdout.log
│       │       ├── worker.stderr.log
│       │       └── artifacts/
│       │           ├── worker_result.json
│       │           ├── dfm_report.json
│       │           ├── dfm_report.md
│       │           ├── dfm_report.pptx
│       │           ├── dfm_highlighted.step
│       │           ├── model.png
│       │           ├── overview.png
│       │           └── DFM-<序号>_<问题>_<视角>.png
│       ├── artifacts/
│       └── reports/
├── tmp/
└── .locks/
```

当前 STEP Analyzer 将本次运行的结果写入 `runs/<run_id>/artifacts/`。项目根目录下的 `artifacts/` 和 `reports/` 是预留目录，不是 M1 STEP 结果的主要读取位置。

## 5. 输入数据

### 5.1 Desktop 附件

Desktop 上传或选择的文件只是 intake 来源，不是 DFM 项目的权威输入。Agent 调用 `dfm_project(add_input)` 后，DFM 才会登记该文件。

### 5.2 项目输入副本

登记 STEP 时会：

1. 检查扩展名和文件大小；
2. 流式计算 SHA-256；
3. 复制到项目 `inputs/`；
4. 校验 ISO 10303-21 格式、B-Rep 声明并记录实体复杂度摘要；
5. 以内容哈希命名；
6. 将 InputRecord 写入 `project_manifest.json`。预检失败不会保留项目输入副本。

InputRecord 主要字段：

```json
{
  "input_id": "input_step_<sha256前16位>",
  "kind": "step",
  "source_name": "用户上传文件名.stp",
  "relative_path": "inputs/input_<sha256前16位>.stp",
  "size_bytes": 123456,
  "sha256": "...",
  "created_at": "...",
  "preflight": {
    "status": "passed",
    "format": "iso-10303-21",
    "brep_representation": "declared",
    "complexity": {"entity_count": 1234}
  }
}
```

STEP 项目在生成可执行 Plan 前必须确认 `material`、`pull_dir` 和 `model_units`。未确认项以稳定 clarification ID 写入 Manifest；`confirm_fact` 保存回答并关闭对应问题。新增输入或确认事实会把既有 Plan 标记为 `invalidated`，需要重新规划。

同名同类型的新输入会以 `supersedes_input_id` 指向旧版本；后续 Plan 仅引用未被替代的活动输入。失效 Plan 会保存 `invalidated_by` 和 `affected_operation_ids`。调用 `dfm_analysis(plan, base_plan_id=...)` 可以从失效 Plan 生成仅包含受影响检查及其依赖的重跑 Plan；例如仅修改拔模方向时，重跑范围为 STEP 加载、拓扑、拔模和倒扣检查，而不是完整检查族。

相同类型且哈希相同的输入会复用既有记录。分析追溯以项目输入副本和哈希为准，不依赖原始附件路径持续存在。

## 6. 项目权威数据：project_manifest.json

`project_manifest.json` 是项目事实的权威来源，聊天记录不是项目数据库。Manifest 当前包含：

- 项目名称、版本和更新时间；
- 输入列表及哈希；
- 用户确认的工程事实；
- Plan 列表；
- Run 列表和状态；
- Run 对应的 artifact 引用；
- 已声明的能力状态。

每次写入会增加 `revision`，并通过锁和原子替换降低并发写坏风险。

### M1.2 边界

`facts`、`clarifications`、`features` 和 `findings` 契约已经存在。M2.5 在保持注塑结果不变的前提下，将压铸拓扑门的失败 Evaluation 归一化为压铸规则引用的项目级 Finding：

- 已确认工艺参数可以写入 `facts` 并参与 Plan 编译；
- 每次 STEP Run 都生成 `measurements.json`，保存输入哈希、算法版本、实际 operations、客观模型测量、问题测量及规则 Evaluation；
- 原始兼容问题仍保存在 `dfm_report.json` 和最终报告中，旧报告格式没有被改写；
- Finding ID 由输入哈希和稳定 Evaluation ID 派生，包含版本化 rule 引用，并引用测量、报告及同次运行的证据制品；
- `ProjectManifest.findings` 是项目级风险浏览入口，精确测量仍以被引用的 `measurements.json` 为准。

## 7. 分析计划与 worker 请求

### 7.1 Manifest 中的 PlanRecord

PlanRecord 保存：

- `process`：由 Plan 固定为 `injection` 或 `die_casting`；
- `process_adapter_version`；
- `scope_id` 与 `scope_version`；
- 输入 ID 和输入哈希；
- 参数值、单位和来源；
- 版本化 operations。

它回答“准备分析什么、使用哪些输入、参数从哪里来、采用哪版规则范围”。

### 7.2 Run 中的 plan_snapshot

启动 Run 时会把完整 Plan 保存为 `plan_snapshot`。即使项目后来增加新事实或新 Plan，既有 Run 仍能回溯当时实际执行的计划。

### 7.3 request.json

`runs/<run_id>/request.json` 是 StepAnalyzer 发给隔离 worker 的请求，主要包含：

- worker schema 版本；
- `run_id`；
- 项目输入文件绝对路径；
- 本次 artifact 输出目录；
- 工艺、范围和分析器版本；
- 有效参数；
- 最大证据问题数量。

`request.json` 是复核“worker 实际收到了什么”的首选文件，但其中的绝对路径属于运行环境路径，迁移到另一台机器后不应直接复用。

## 8. 运行过程数据

### 8.1 Run 状态

```text
queued ──> running ──> succeeded
   │          ├──────> failed
   │          ├──────> cancelled
   │          └──────> blocked
   ├─────────────────> failed
   ├─────────────────> cancelled
   └─────────────────> blocked
```

RunRecord 同时保存：

- analyzer 名称和版本；
- Plan ID 与 Plan 快照；
- stage 和 progress percent；
- heartbeat；
- owner PID 与 runtime ID；
- error；
- artifact 列表；
- 三个诊断日志的相对路径。

### 8.2 events.jsonl

`events.jsonl` 每行是一个 UTF-8 JSON 对象，用于记录 worker 的结构化事件，例如：

- `progress`：阶段与百分比；
- `heartbeat`：长任务存活信号；
- `artifact`：新制品名称和类型；
- `error`：结构化错误码和消息；
- `completed`：worker 结果文件。

它适合时间线分析和 UI 进度恢复，不应把普通 stdout 文本当作权威状态。

### 8.3 worker.stdout.log

保存 worker 完整标准输出，包括带 `__HERMES_DFM_EVENT__` 前缀的原始 JSONL 协议行及分析器普通输出。主要用于：

- 检查事件是否实际发出；
- 定位进度停在哪个阶段；
- 排查事件解析或编码问题。

### 8.4 worker.stderr.log

保存警告和异常堆栈，主要用于排查：

- STEP/B-Rep 读取失败；
- OpenCascade 几何计算异常；
- 渲染或证据图片失败；
- PPTX 报告生成失败；
- 子进程依赖、编码或退出异常。

## 9. 分析结果数据

| 文件 | 类型/用途 | 主要使用者 |
| --- | --- | --- |
| `worker_result.json` | worker 原始结果、输入哈希、参数、artifact 元数据 | Analyzer、开发诊断 |
| `measurements.json` | 版本化 Measurement、Evaluation、实际 operations 和几何引用 | 后续 Finding 归一化、系统集成、开发诊断 |
| `dfm_report.json` | 结构化 DFM 分析结果 | 系统集成、后续归一化 |
| `dfm_report.md` | 可读文本报告和兼容交付 | Agent、开发者 |
| `dfm_report.pptx` | 当前主要用户交付报告 | Desktop 用户 |
| `dfm_highlighted.step` | 高亮或标记问题的 STEP | CAD 复核 |
| `model.png` | 模型整体图 | 报告封面/模型概览 |
| `overview.png` | 问题总览 | 报告摘要 |
| `DFM-*.png` | 具体问题证据图 | 问题详情、PPTX |

M1.2 中只有 Plan 包含 `render_evidence` 时才生成证据图片和高亮 STEP。每个进入重点证据范围的问题最多生成：

- 正视图 `front`；
- 斜视图 `oblique`；
- 剖视图 `section`。

并非所有发现都会生成三张图片。是否生成取决于问题类型、证据渲染是否成功以及 `max_rendered_findings` 配置。

## 10. 数据追溯关系

```text
项目输入文件
  └─ SHA-256 / InputRecord
       └─ PlanRecord.input_ids + input_hashes
            └─ RunRecord.plan_snapshot
                 └─ request.json
                      └─ worker_result.json / dfm_report.json
                           └─ evidence PNG / highlighted STEP / PPTX
                                └─ ArtifactRecord.relative_path
```

复核一个问题时，推荐顺序为：

1. 从 PPTX 或 `dfm_report.json` 找到问题编号；
2. 在同一 Run 的 artifact 目录找到对应证据图片；
3. 查看 `worker_result.json` 中的原始测量或 issue；
4. 查看 `request.json` 中的有效参数；
5. 查看 Manifest 中的 Plan 快照、输入 ID 和哈希；
6. 必要时使用项目 `inputs/` 中的 STEP 复算。

## 11. 如何找到最近一次分析

PowerShell 示例：

```powershell
$dfmRoot = Join-Path $env:USERPROFILE ".hermes\workspace\dfm"

# 最近更新的项目
Get-ChildItem "$dfmRoot\projects" -Directory |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 FullName, LastWriteTime

# 某项目最近的 Run
Get-ChildItem "<项目目录>\runs" -Directory |
  Sort-Object LastWriteTime -Descending |
  Select-Object FullName, LastWriteTime

# 查看结构化事件
Get-Content "<Run目录>\events.jsonl" -Encoding UTF8

# 查看错误日志
Get-Content "<Run目录>\worker.stderr.log" -Tail 200 -Encoding UTF8

# 查看结果文件
Get-ChildItem "<Run目录>\artifacts" -File |
  Select-Object Name, Length, LastWriteTime
```

环境和能力自检：

```powershell
python .\hermes dfm doctor --json
```

`dfm doctor` 只验证配置、工作区、worker 解释器、OCC/PPTX 依赖和能力声明，不代表某个具体 STEP 已经分析成功。

## 12. 成功、失败和中断的判断

### 成功

- Manifest 中对应 Run 为 `succeeded`；
- `events.jsonl` 有且仅有一个有效 completion 结果；
- `worker_result.json` 可解析；
- Run artifact 已登记并且文件存在；
- JSON/PPTX 能打开，证据引用与图片对应。

### 失败

- Run 为 `failed`；
- RunRecord.error 包含结构化错误；
- 优先查看 `worker.stderr.log`，再结合 `events.jsonl` 和 stdout；
- 如果 worker 已生成部分文件但未登记为 artifact，不应把这些文件视为正式交付结果。

### 取消

- Run 为 `cancelled`；
- 已登记的诊断数据可以保留；
- 部分生成的报告或图片不代表完整分析。

### 阻塞

- Run 为 `blocked`；
- 常见原因包括能力未实现、依赖缺失、Plan 不可执行或输入条件不足；
- 应补充条件或恢复依赖后创建新 Plan/Run，不直接篡改旧 Run。

## 13. 保留、清理与安全

- `project_manifest.json`、`inputs/`、`runs/` 和已登记 artifact 是可审计数据，不应随聊天清空。
- `tmp/`、锁和未登记的临时文件可以按清理策略处理。
- `keep_failed_runs: true` 时保留失败 Run，便于定位 OCC 和报告问题。
- STEP、报告和证据图片可能包含产品知识产权，生产环境应限制工作区访问权限并设置备份、保留和安全删除策略。
- Manifest 保存 canonical 相对路径；工具返回给 Desktop 时可以附加当前环境的绝对路径。不要把绝对路径当成跨机器稳定标识。
- 不要手工编辑运行中的 Manifest、`events.jsonl` 或 artifact。需要更正事实时创建新事实、Plan 或 Run。

## 14. 活文档更新规则

以下变化必须与代码在同一个变更中更新本文：

| 变化 | 必须更新的章节 |
| --- | --- |
| 新增输入类型或制造工艺 | M1 适用范围、输入数据、调用流程 |
| 修改工作区或 artifact 路径 | 数据根目录、真实目录结构、排查命令 |
| 修改 Manifest/Plan/Run/worker schema | 对应数据说明和追溯关系 |
| 新增/删除报告或证据文件 | 分析结果数据 |
| 修改状态机、进度或取消语义 | 运行过程、成功失败判断 |
| 完成 Finding/Measurement 归一化 | Manifest M1 边界、结果读取优先级 |
| 进入新里程碑 | front matter 的 `milestone`、能力矩阵和文档日期 |

更新时遵守：

1. 当前事实与未来计划分开写；
2. 目录结构以真实代码和一次 E2E Run 为准；
3. 示例只使用合成或脱敏数据；
4. 不冻结容易变化的 issue 数量；
5. 修改后至少用一个真实 Run 核对文件名、路径、状态和 artifact 登记。

## 15. 相关文档

- [DFM Hermes Agent 开发目标与路线图](plans/2026-07-13-dfm-hermes-agent-development-roadmap.md)
- [DFM 部署环境定义](dfm-deployment-environment.md)
