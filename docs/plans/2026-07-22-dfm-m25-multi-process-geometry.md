# DFM M2.5 多工艺与多几何格式架构适配实施计划

## 1. 目标与不变量

M2.5 插在当前 M3 之前，先解决“注塑 STEP 单一路径”向“多工艺、可扩展几何格式”
演进时的架构边界。目标不是一次完成全部压铸算法或宣称支持 Parasolid，而是让压铸
能够独立演进，让未来 `x_t` Reader 能接入同一几何计算层，并保证已有注塑 STEP
产品 DFM 分析无回归。

以下兼容性不变量必须保持：

- 未显式选择工艺的既有项目仍使用 `injection`。
- 注塑继续使用 `injection.legacy-baseline@1.1.0` 和既有 issue catalog 版本。
- 同一 STEP、事实、配置和工具版本产生等价的 Plan operations、有效参数、测量、
  Evaluation、Finding `rule_ref`、Artifact 和报告。
- 现有 `dfm_project`、`dfm_analysis` 工具 Schema 和 Desktop 交互不增加第二套入口。
- 压铸或 Parasolid 依赖缺失只阻塞对应组合，不降低注塑 STEP capability。
- 任何未批准的压铸阈值或检查都必须明确不可用，不能继承注塑默认值。

## 2. 用户流程

### 2.1 现有注塑 STEP

```text
上传 STEP
  → 默认/显式选择 injection
  → 注塑前置事实澄清
  → injection scope 编译 Plan
  → STEP Reader 加载 B-Rep
  → 现有检查、Finding 和报告
```

该路径在 M2.5 前后保持行为等价。

### 2.2 压铸 STEP

```text
上传 STEP
  → 用户选择 die_casting（不允许 Agent 仅凭外形猜测）
  → 询问压铸 scope 真正需要的事实
  → DieCastingProcessAdapter 选择已批准规则和 operations
  → STEP Reader 加载同一种 B-Rep
  → 仅执行压铸 capability 已实现的检查
  → 压铸规则 Evaluation、Finding 和报告
```

可复用的几何测量不等于可复用的工艺判断。例如壁厚、拔模角、倒扣和圆角可以共享
B-Rep calculator，但适用区域、阈值、严重程度和建议必须来自压铸规则。

### 2.3 压铸 `x_t`

```text
上传 x_t
  → Parasolid 格式预检
  → 查询 Reader、支持版本和许可证 capability
  → Reader 不可用：返回 dependency_missing/unsupported_format_version
  → Reader 可用：转换为统一 GeometryModel
  → 后续使用与 STEP 相同的压铸 Plan 和 B-Rep calculators
```

M2.5 首先保证前半段能力状态真实。只有真实 Parasolid SDK 或经过批准的转换器通过
保真度、许可证和部署验收后，才允许后半段进入生产运行。

## 3. 目标模型

必须把以下维度分开：

| 维度 | 示例 | 责任 |
| --- | --- | --- |
| 制造工艺 | `injection`、`die_casting` | 选择事实要求、规则 scope、operations 和评价方式 |
| 几何格式 | `step_ap203`、`step_ap214`、`step_ap242`、`parasolid_xt` | 预检并读取精确几何 |
| 资料组合 | `geometry_only`、`drawing_only`、`geometry_and_drawing` | 表达项目有哪些证据来源 |
| 几何表示 | `brep_solid`、`brep_sheet`、`mesh` | 决定 calculator 的数学能力 |
| 检查能力 | `wall_thickness`、`draft`、`undercut` 等 | 声明输入、事实、参数和输出契约 |

目标调用链：

```text
InputRecord.format
  → ParasolidXTPreflight / StepGeometryReader
  → GeometryModel
  → ProcessAdapter.compile(facts, scope, geometry_capabilities)
  → CheckRegistry.resolve(operation, representation)
  → Measurement
  → process-specific Rule Evaluation
  → Finding
```

数据库或规则配置只能引用稳定的 `operation_id`/`calculator_id`，不能保存任意 Python
代码路径。

## 4. 工作包

### WP1：冻结注塑兼容性基线

- 记录现有注塑 STEP Plan、参数来源、operation 顺序和输入哈希关系。
- 为 Measurement/Evaluation/Finding 建立关系断言，不冻结无意义的数量快照。
- 覆盖默认工艺、显式 `injection`、事实变更、增量重规划和真实 OCC E2E。
- 将这些测试作为后续每个工作包的回归门。

### WP2：拆分项目工艺与输入格式

- 为项目增加明确的 `process` 选择和来源，不再依赖 `domain=injection_molding` 推断。
- InputRecord 增加稳定 `format_id` 和 `representation`；保留旧 Manifest 的迁移读取。
- 将 `input_mode` 收敛为资料组合语义，旧值 `step`/`fusion` 通过 schema migration 映射。
- 改造 capability 返回，使其同时报告 process、reader、representation 和 operation 状态。
- 新增工艺事实变更导致 Plan 失效的规则；既有 Run 快照永不重写。

### WP3：前置事实声明化

- 将 `DFMService._STEP_REQUIRED_FACTS` 替换为 ProcessAdapter/scope 的
  `required_facts`，支持按 operation 条件合并。
- 注塑首轮迁移保持现有 `material`、`model_units`、`pull_dir` 行为等价。
- 压铸候选事实先由批准的检查清单决定，可能包含 `alloy`、`casting_method`、
  `model_units`、`pull_dir` 和质量目标；没有消费者的事实不提前加入澄清。
- Clarification ID 包含稳定事实名而非文件格式；切换工艺时关闭不再适用的问题并创建
  新工艺问题，禁止 Agent 自行回答。

### WP4：压铸 ProcessAdapter 与规则隔离

- 新增 `DieCastingProcessAdapter` 和独立版本化 scope/catalog 目录。
- 首先返回真实 capability 矩阵；没有规则或 calculator 的 operation 明确 blocked。
- 与压铸工程人员批准第一批垂直检查。建议从能够复用确定性几何测量、但规则独立的
  项目开始，例如最小/最大壁厚、拔模角、倒扣、圆角或厚薄突变；最终清单和阈值由
  代表性压铸语料决定，不能从注塑 scope 复制。
- Finding 使用压铸规则引用，例如 `die_casting.<catalog>@<version>:<rule_id>`。
- 报告明确显示工艺、合金/材料事实、规则集版本和不具备能力的检查。

### WP5：统一 B-Rep 读取和检查边界

- 定义 `GeometryReader`、`GeometryModel`、`GeometryProvenance` 和
  `GeometryCapability` 契约。
- 先用 `StepGeometryReader` 包装当前 OCC 载入路径，不改变 worker 输出。
- 识别 `geometry/step/checks` 中真正只依赖 B-Rep 的 calculator，逐个迁移到
  `geometry/brep/checks`；STEP 特有解析、拓扑 ID 和证据导出仍留在 Reader/adapter。
- CheckRegistry 以 representation 和 calculator capability 选实现，不以工艺复制函数。
- 每次迁移都运行注塑基线及 STEP 证据引用回归。

### WP6：Parasolid `x_t` 预留和 PoC

- 增加 `.x_t`（后续可含 `.x_b`）独立 format ID，不伪装成 STEP。
- 实现轻量预检契约：格式签名、Parasolid 版本、文件截断、文件大小和 reader 支持状态；
  无可靠解析器时不从文本内容猜测完整 Body/Face 信息。
- 定义 `ParasolidXTPreflight` 的轻量登记边界和 HTTP NX Backend capability；重型
  NX/Parasolid SDK 只在远端 NX Worker 中加载。
- 评估原生 Parasolid SDK和可信商业转换器两条路线，记录许可证、可分发性、支持版本、
  单位、公差、属性、Body 数量、healing 行为和失败模型。
- 使用同源 STEP/`x_t` 样件比较包围盒、面积、体积、拓扑有效性、壁厚、拔模和倒扣；
  采用工程容差与空间证据关系，不比较不稳定 Face ID。
- 若使用派生 STEP，Manifest 保存原始 `x_t`、派生输入、转换器版本/参数/哈希和
  `converted_from` 谱系。

### WP7：能力矩阵与端到端验收

至少验证：

| 工艺 | 格式 | 预期 |
| --- | --- | --- |
| 注塑 | STEP | 与 M2 行为等价且可运行 |
| 压铸 | STEP | 仅已批准 operations 可运行，其余明确 blocked |
| 注塑 | `x_t` | Reader 未批准时只阻塞该组合 |
| 压铸 | `x_t` | Reader 未批准时只阻塞该组合 |
| 未知工艺 | STEP | 要求用户选择或返回 unsupported process |
| 注塑 | 损坏 STEP | 保持现有预检错误 |
| 压铸 | 不支持版本 `x_t` | 返回具体 NX Backend 格式 capability 错误 |

另外验证压铸运行失败、Parasolid dependency 缺失和格式错误不会修改注塑 Plan、Run、
规则缓存或默认 capability。

## 5. 建议代码落点

```text
tools/dfm/
├── geometry/
│   ├── contracts.py
│   ├── readers/
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── step.py
│   └── brep/checks/
├── project/
│   └── parasolid_preflight.py
├── backends/nx/
│   ├── contracts.py
│   └── client.py
├── processes/
│   ├── injection.py
│   └── die_casting.py
├── scopes/
│   ├── injection/
│   └── die_casting/
└── workers/
    └── step_worker.py
```

只在有第一个真实消费者时创建模块。M2.5 不新增核心模型工具、不修改 Agent Loop，继续
使用现有 `dfm_project`、`dfm_analysis`、clarify 和 Desktop Artifacts。

## 6. 实施顺序与决策门

```text
注塑基线
  → 契约拆分与旧 Manifest 迁移
  → 声明式 required_facts
  → 压铸 adapter/capability
  → 首条压铸 STEP 垂直检查
  → B-Rep 边界逐项抽取
  → x_t Reader/转换 PoC
  → 能力矩阵与真实 E2E
```

Parasolid 执行 capability 只有在以下决策门全部通过后才能从 `not_implemented` 改为
`available`：

1. SDK/转换器许可证允许目标部署和分发方式；
2. 支持目标客户实际使用的 Parasolid 版本；
3. 单位、公差、实体和失败状态能够可靠读取；
4. 同源 STEP/`x_t` 工程不变量达到批准误差；
5. 进程隔离、超时、取消和资源限制通过；
6. 真实压铸样件 E2E 通过且证据可复核。

## 7. M2.5 明确不做

- 不在没有规则来源和样件验收时批量编造压铸阈值。
- 不把注塑 scope 改名后当作压铸规则。
- 不因为 `.x_t` 扩展名可登记就声明能够几何分析。
- 不把 Parasolid 商业依赖导入 Hermes 主进程。
- 不同时实现 OCR、二维工程特征或图纸到三维拓扑融合；这些仍属于 M3–M5。
- 不建设第二套 Desktop DFM 聊天或上传页面。

## 8. 完成定义

M2.5 完成时应同时满足：

- 注塑 STEP 完整回归和真实 OCC E2E 通过；
- 工艺、格式、资料组合、表示和 operation capability 在契约中可独立表达；
- 注塑和压铸拥有独立 adapter、scope provenance、前置事实和规则引用；
- 至少一条经工程批准的压铸 STEP 检查形成 Measurement → Evaluation → Finding 闭环；
- 未实现的压铸检查和未批准的 `x_t` Reader 返回真实、局部的不可用状态；
- `x_t` 轻量输入预检和 HTTP-only NX Backend Client 已实现；未配置
  `dfm.nx.endpoint` 时保持 `dependency_missing`，服务端格式或 calculator 未认证时
  保持 `not_implemented`，且不影响 STEP 运行环境；
- 路线图、运行手册、部署说明和 capability 文档与真实代码一致。
