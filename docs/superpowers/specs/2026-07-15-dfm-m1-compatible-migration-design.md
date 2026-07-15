# DFM M1 兼容迁移设计

**状态：** 设计方向已批准  
**日期：** 2026-07-15  
**里程碑：** M1——现有行为基线与 STEP 分析器适配

## 1. 目标

M1 将 Django 侧已跑通的 STEP 分析器迁入 Hermes M0 基础框架，但不把 Django、DeepAgents、MinIO、请求上下文或业务模型变成运行时依赖。第一版生产能力只支持注塑 `injection`。

迁移先保持经批准的旧分析器测量和证据行为，再渐进拆分算法；同时建立真实消费者所需的工艺适配器、默认分析范围、版本化 worker 协议和计划快照边界。

## 2. M1 范围

M1 包含：

- M0 `Analyzer` 契约后的真实 `StepAnalyzer`；
- 仅注册 `injection` 的 ProcessAdapter；
- argv 驱动、独立子进程运行的 STEP worker；
- Windows/POSIX 的超时、取消和进程树终止；
- 版本化的 worker 请求、事件、结果与分析计划快照；
- `injection.legacy-baseline` 默认分析范围；
- JSON、Markdown、PNG 和高亮 STEP artifact 登记；
- Django 旧分析器与 Hermes worker 的代表性对比夹具；
- 每个生效参数的值、单位和来源记录。

M1 不包含 OCR、2D 特征识别、STEP/图纸映射、完整 Measurement/Finding 规则引擎、旧系统不存在的正式标准码、DFM 专用 Desktop 页面、非注塑工艺或第二套 Agent Loop。

## 3. 现有基线

Django 通过 CLI 调用大型 `dfm_analyze.py`。虽然 `process` 接受 `generic`、`injection` 和 `machining`，旧实现没有 ProcessAdapterRegistry；三种模式运行同一条广泛的检查流水线，工艺差异主要是少量默认参数和报告标签。

Django 编排层还负责输入发现、子进程、DeepAgents、MinIO 和请求上下文。这些不属于工程分析器，不能迁入 Hermes worker。

M0 的 Plan 目前只保存分析器键和 capability 状态，尚未冻结工艺、scope、执行步骤、参数及来源。

## 4. 分层职责

### 4.1 Hermes Agent 与 Skill

现有 `AIAgent` 负责理解用户意图、提出候选工艺和分析范围、追问、调用 DFM 工具及解释结果，不计算工程数值。

`skills/manufacturing/dfm-analysis/SKILL.md` 是模型操作手册：要求先检查 capability，M1 只使用 injection，用户未指定指标时选择默认 scope，确认事实写入项目，且禁止编造测量值、规则和标准。Skill 不包含 CAD、存储或进程代码。

### 4.2 工具与 DFMService

`tools/dfm_tool.py` 继续只暴露 `dfm_project` 和 `dfm_analysis`，DFM 仍为默认关闭的独立 toolset。

Agent 提出候选计划，`DFMService` 从 Manifest、输入、确认事实、ProcessAdapter、scope 和 analyzer capability 中编译并校验可执行计划。Service 必须拒绝未知工艺、未知检查、非法单位、缺失前置事实以及模型臆造的规则/标准标识。

可执行计划至少冻结：

- process key 与 adapter version；
- scope ID 与 version；
- 输入 ID 与哈希；
- analyzer/worker version；
- 有序操作及依赖；
- 生效参数、单位和 provenance；
- capability 和缺失条件；
- 已审定的 rule-set 标识。

Run 只执行已持久化的 Plan 快照。运行期间不得回调模型修改计划；发现缺失条件时显式 blocked/failed，后续工具结果回到 Agent，再确认事实并建立新的 Plan revision。

### 4.3 StepAnalyzer、Runtime 与 Worker

`tools/dfm/analyzers/step.py` 选择 STEP 输入、解析 ProcessAdapter、构造 worker 请求、消费事件并登记安全 artifact。

`tools/dfm/runtime/process.py` 负责 argv 启动、输出流、超时、取消轮询以及 Windows/POSIX 进程树终止；这些操作不堆进 StepAnalyzer。

`tools/dfm/workers/step_worker.py` 是独立入口，不导入 Django、Hermes Agent、Desktop、DeepAgents、MinIO 或业务模型。父进程使用 `shell=False` 启动它；stdout 只承载版本化 JSON Lines 事件，stderr 用于诊断。

### 4.4 ProcessAdapter 与几何模块

ProcessAdapter 放在 `tools/dfm/processes/`，因为工艺未来会组合 STEP、图纸要求、用户事实和规则包，不只属于 STEP。

M1 的最小协议包含稳定 key/version、capability、参数规范化、默认 scope 选择和 worker 请求构造。注册器只有真实消费者 `injection`；其他工艺返回 `unsupported_capability` 和支持列表。

为了先固定基线，M1 injection 仍运行旧完整流水线，即使旧检查中存在偏机加工的命名；这不代表 Hermes 已支持 machining。基线稳定后才按 loader、topology、measurement、checks、rendering 和 highlighting 渐进拆分。

OpenCascade 模块拥有全部确定性测量；Agent、Service 和规则层都不得生成几何数值。

## 5. 目标目录

```text
skills/manufacturing/dfm-analysis/SKILL.md

tools/dfm/
├── analyzers/step.py
├── processes/
│   ├── base.py
│   ├── registry.py
│   └── injection.py
├── scopes/injection/legacy_baseline_v1.json
├── runtime/
│   ├── jobs.py
│   ├── process.py
│   └── events.py
├── workers/step_worker.py
├── geometry/step/legacy_analyzer.py
├── contracts.py
├── service.py
└── errors.py
```

旧算法兼容模块只有在基线测试证明行为未改变后才进一步拆分。

## 6. 数据与调用关系

Agent 可以提交候选 process、scope、检查方向及确认参数。省略检查表示使用工艺默认 scope，不表示不做分析。

Service 把候选意图展开成不可变 Plan。M1 未指定更窄范围时使用 `injection.legacy-baseline`。每个参数来源必须是 `user_confirmed`、`project_fact`、未来的 `drawing_requirement`/`customer_profile`，或 `injection_legacy_default` 之一。

worker 请求包含 schema version、run ID、受约束的输入/输出路径、process、scope、参数及预期 analyzer version。worker 事件只允许：

- `progress`：阶段和 0–100 百分比；
- `artifact`：类型和项目内相对路径；
- `completed`：结果路径和 worker version；
- `error`：稳定错误码和安全消息。

未知或畸形事件只能成为诊断，不能驱动状态迁移。worker 结果记录输入哈希、process、scope、参数与来源、版本、旧 stats/issues 和 artifact 引用。M1 保留 raw legacy issue，不提前把它声明为稳定 Hermes Finding。

控制流为：

```text
Agent -> dfm_analysis(plan) -> DFMService -> persisted Plan -> Agent
Agent -> dfm_analysis(start) -> JobManager -> queued/running -> Agent
Agent -> dfm_analysis(status/result) -> persisted Run -> Agent

JobManager -> StepAnalyzer -> ProcessAdapter -> ProcessRunner
           -> STEP worker -> OpenCascade -> artifacts/result
```

后台 worker 不调用模型，从而保护提示词缓存、消息角色交替、可复现性和恢复语义。

## 7. 默认范围与未来图纸要求

M1 提供版本化的 `injection.legacy-baseline`，如实记录实际阈值及 `legacy_internal_profile` 来源，不编造 GB、ISO、企业标准码。

未来的 `RequirementRecord` 用于承载图纸或用户给出的产品专属要求，保留原文、输入/页码/区域证据、规范化指标/数值/单位、适用范围、置信度和确认/冲突状态。

后续计划编译按以下来源解析有效要求，但不丢失 provenance：

1. 用户确认的项目专属要求；
2. 有充分证据的图纸明确要求；
3. 审定的客户/产品 profile；
4. 工艺默认 scope。

冲突不能静默覆盖，必须生成澄清条件并把控制权返回 Agent。M1 的 STEP-only 参数来自确认事实或 injection 默认 scope；未来从图纸解析出的有效参数仍使用同一 worker 契约。

三种输入模式遵循以下边界：

- 只有 STEP：使用确认事实和 injection 默认 scope；缺少不可默认的关键条件时要求澄清。
- 只有 2D 图纸：未来可提取需求并做资料/规则预检查，但不能伪造精确三维几何结果。
- STEP + 2D：图纸提供产品要求，STEP 提供几何测量，融合层进行可追溯比较。

## 8. 错误与恢复

- 缺少 OpenCascade：`dependency_missing`，不生成伪 artifact。
- 非 injection：`unsupported_capability`，返回 `supported_processes=["injection"]`。
- 缺少输入/事实：Plan blocked 并列出前置条件。
- 非法 Plan/参数：创建进程前返回稳定校验错误。
- 超时：终止进程树并持久化 `failed/worker_timeout`。
- 取消：终止进程树并持久化 `cancelled`。
- 非零退出：保存净化后的稳定错误；安全诊断可作为 artifact。
- 进程重启：沿用 M0，未完成 Run 变为 `blocked/runtime_restarted`。
- 越界 artifact：拒绝并失败，不能暴露项目外路径。
- 部分输出：没有有效 completed/result 时不能判定成功。

## 9. 验证方案

契约测试覆盖工艺注册、injection-only capability、Plan 快照/provenance、Run-Plan 关联、worker schema 和未知事件。

进程测试使用真实小型子进程验证带空格/中文路径的 argv、stdout/stderr 分离、超时、取消、进程树终止和 artifact 边界。

基线测试使用已批准的脱敏或合成 STEP，比较旧 Django 分析器与 Hermes worker 的 B-Rep 有效性、包围尺寸、面积/体积、代表性孔径、壁厚、拔模角、issue metric/topology refs 及证据文件。测试比较数值关系和批准误差，不冻结无意义的 issue 总数。

Hermes 集成测试使用临时 `HERMES_HOME` 和真实工具发现，完成启用 toolset、建项目、登记 STEP、生成 injection Plan、启动/轮询真实 worker、验证 Plan/Run/result/artifact、取消、重启恢复，并证明关闭 toolset 时 DFM schema 不出现。

## 10. M1 退出标准

- 安装真实依赖后 StepAnalyzer capability 为 available。
- injection 是唯一支持工艺，其他工艺显式失败。
- worker 不导入 Django 业务基础设施。
- 同输入、显式 profile 下，批准夹具得到等价测量和证据。
- Plan、process、scope、参数/provenance、版本和输入哈希均被持久化。
- 成功、失败、超时、取消和重启都留下可恢复 Run。
- artifact 位于项目内并可被现有 Desktop Artifacts 发现。
- 不产生模型生成的测量、标准码或占位 Finding。
- M0 公共工具面及默认关闭行为保持不变。

## 11. 后续演进

M2 规范化 Measurement/Finding 并完成 STEP 对话闭环；M3 提取带页码/区域证据的图纸文本和产品要求；M4 识别图纸特征；M5 融合图纸要求、STEP 测量、用户事实和默认 scope；M6 引入审定的版本化知识/规则包和正式标准引用。

未来增加真实工艺 adapter 和规则/scope 包时，不修改 Agent Loop、公共 DFM 工具、项目存储主结构、worker transport 或 Desktop 上传协议。
