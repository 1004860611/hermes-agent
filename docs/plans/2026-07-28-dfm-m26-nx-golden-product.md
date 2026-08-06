# DFM M2.6 NX 黄金产品纵向闭环实施计划

## 1. 目标

选取一个模具工程师已经完成 DFM 分析的真实或脱敏产品 `.x_t` 文件，将其确认事实、
所需指标、规则阈值、问题区域和工程结论转换为可执行、可追溯的验收基线。完成 NX
Server、NX C++ 插件、初始压铸规则、Hermes 规划、Measurement、Evaluation、Finding、
Evidence 和报告的第一条真实产品闭环，并由工程师复核结果。

M2.6 验证的是“第一条业务纵向闭环”，不是仅验证 NX 能打开文件，也不宣称一个产品
可以覆盖所有压铸产品。

## 2. 生产链路与人工验收边界

### 2.1 生产 DFM 链路

```text
用户上传 x_t
→ Hermes 项目和确认事实
→ Rule Set / Plan
→ HttpNXBackendClient
→ NX Server / NX C++ Plugin
→ measurements.json + scalar_field + render_scene + topology_map
→ Hermes EvaluationEngine
→ evaluations.json
→ Hermes FieldEvidenceEngine
→ evidence_geometry.json + PNG + evidence_records.json
→ evaluated Finding / Report
→ 只读 Run Bundle
```

这是 DFM 智能体正式功能。其输入、状态和结果进入项目 Manifest。

### 2.2 研发验收链路

```text
只读 Run Bundle + Engineer Ground Truth
→ 模具工程师逐项人工核对 Measurement / Finding / Region / Report
→ 人工记录一致项、差异、原因和处理结论
→ 模具工程师签字
```

这是 M2.6 的人工研发验收活动，不是 DFM 智能体功能，不开发自动比较程序。

### 2.3 人工验收边界

第 21 步只由人执行，并满足：

- 不开发 Ground Truth Comparator、比较脚本、比较服务或专用 CI；
- 不注册新的 Hermes model tool、toolset、Skill、API 或 Desktop 功能；
- 人工核对只在生产 Run 完成后进行，不介入 `DFMService`、`JobManager`、
  `EvaluationEngine` 或 `FindingEngine`；
- 不读取或写入运行中的 Manifest，也不修改 Measurement、Evaluation、Finding、severity
  或 capability；
- 不把 Ground Truth 发送给 Agent，避免答案泄露到生产分析；
- 工程师只核对已完成、不可变的 Run Bundle 和界面/报告结果；
- 人工核对记录仅作为研发验收和工程签字证据，不回写生产分析结果。

推荐数据边界：

```text
hermes-agent/                  # 生产代码，只生成可追溯 Run/Run Bundle
受控验收存储/                 # 非代码：黄金产品、工程师基线、人工核对表、签字记录
```

真实产品和工程师结论不提交公共源码仓库。M2.6 不新增验证代码目录或独立比较仓库。

## 3. 黄金产品包

黄金产品不是单个 `.x_t`，而是一组受控验收资产：

```text
golden-product-01/
├── input/
│   ├── product.x_t
│   ├── product.step                 # 可选，同源对照
│   └── drawing.pdf                  # 可选，若工程结论依赖图纸
├── facts/
│   └── confirmed_facts.json
├── requirements/
│   ├── required_metrics.json
│   └── traceability_matrix.json
├── rules/
│   └── approved_rule_set.json
├── ground_truth/
│   ├── manual_check_baseline.xlsx   # 指标、期望结果、容差、区域和问题清单
│   └── engineer_report.pdf
├── evidence/
│   ├── annotations.json
│   └── reference_images/
└── approval/
    └── sign_off.pdf                 # 或受控审批系统记录
```

真实产品数据、Ground Truth、人工核对表和工程师报告属于产品知识产权，存放在访问受控的
私有存储，不提交公共源码。Hermes 仓库只保存与生产契约有关的 Schema、脱敏示例和测试。

## 4. Ground Truth 的产生和冻结

Ground Truth 由模具工程师、架构负责人和模块负责人共同整理，作为人工核对基线；不能
只保留一份缺少指标、区域和判定依据的历史 PDF。

### 4.1 确认事实

至少包括：

```json
{
  "process": "die_casting",
  "alloy": "由工程师确认",
  "casting_method": "由工程师确认",
  "model_units": "mm",
  "pull_dir": [0.0, 0.0, 1.0]
}
```

### 4.2 指标和问题

每个指标定义：

- metric/calculator ID；
- 工程师参考值或参考区间；
- 单位；
- 绝对/相对允许误差；
- 适用区域；
- 计算方法约定；
- 规则和阈值；
- 对应问题、严重程度和证据。

### 4.3 区域标注

不把不稳定 Face ID 作为跨 Backend 唯一真值。区域基线使用：

- 空间 bbox；
- 参考点/曲线/面片；
- 区域面积或采样比例；
- 工程语义描述；
- 工程师标注图片；
- NX persistent ID 仅作为同 Backend 辅助信息。

### 4.4 冻结和变更

冻结版本包含产品输入 SHA-256、工程师基线版本、规则版本、标注版本、批准
人和时间。任何修改发布新版本并说明原因，禁止为了让测试通过静默改真值。

## 5. 追溯矩阵

M2.6 业务 Calculator 开发开始前必须完成黄金产品追溯矩阵和
[DFM/NX Production Task Contract](../dfm-nx-task-contract.md) 联合评审。稳定 ID 的职责如下：

| ID | 含义 | 示例 |
| --- | --- | --- |
| Rule ID | 确定性工程判据 | `die_casting.min_draft.fixed_half` |
| Metric ID | 业务上要回答的问题 | `dc.geometry.draft.fixed_half` |
| Calculator ID | 通用、Backend 无关的算法能力 | `measure_draft` |
| Operation ID | 当前 Plan 中的一次任务实例 | `draft.fixed_half` |
| Measurement ID | 当前 Run 中的一条客观结果 | `measurement_draft_fixed_half_min` |
| Field/Scene/Map Artifact ID | 客观局部场、渲染网格和拓扑映射 | `field_draft_fixed_half` |
| Evidence ID | Hermes 判定后生成的截图证据 | `evidence_run_01_1` |

方向、区域、工艺和黄金产品身份不能编码进 Calculator ID。六方向拔模生成六个 Operation，
通过任务级 `arguments` 分别引用方向和区域，但共同使用 `measure_draft`。

黄金产品追溯矩阵必须完成：

| 工程问题 | Rule ID | Metric | Calculator | Backend | Measurement | Evaluation | Finding | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 示例：局部薄壁 | `die_casting.min_wall` | `thickness_mm` | `measure_wall_thickness` | NX | `measurement_*` | `evaluation_*` | `finding_*` | region/image |

该矩阵决定插件和规则开发范围。第一阶段只实现黄金产品真实需要的 calculator，不以
“尽可能多做功能”代替闭环验收。

## 6. 生产模块工作包

### WP0：M2.6 数据契约联合评审

- 冻结 Rule/Metric/Calculator/Operation/Measurement/Region ID 词典；
- 正式 Calculator ID 使用 `inspect_topology`、`measure_draft`、
  `measure_wall_thickness` 和 `inspect_undercut`；
- 评审唯一 Schema 1 的 `calculator_id`、`metric_ids`、`required_quantities`、`required_artifacts` 和已解析 `arguments`；
- 评审 RuleBinding、结构化 Calculator capability、Region、Measurement、ScalarField、RenderScene、TopologyMap 和 EvidenceRecord 回链字段；
- Hermes 与 NX Server/C++ 使用同一组 JSON fixture 做双向契约测试；
- NX Server 和 Hermes 只实现同一份生产数据契约，不维护 demo 双轨。

WP0 不依赖真实 P0 数值算法，可以与黄金产品事实冻结、NX Server 上传/Job/topology 技术链
并行；WP2、WP4、WP5 的 P0 业务实现必须在 WP0 通过后开始。

### WP1：产品事实和初始 Rule Set

- 将工程师确认事实写入现有 Fact/Clarification 契约；
- 建立独立压铸 Rule Set，不复制注塑阈值；
- 保存规则 ID、version、source、operator、unit、priority 和 hash；
- 对黄金产品形成 Effective Rule Set 快照；
- 缺失规则返回 `rule_not_found`，不由 LLM 补值。

### WP2：产品 Plan

- required metrics 与 calculator 一一映射；
- 生成依赖有序 calculator DAG；
- 六方向任务分别使用唯一 Operation ID，并通过 `arguments` 引用方向和区域；
- 所需 calculator 必须在 NX capability 中为 `certified`；
- 每个任务必须通过 Calculator 参数、输出 Quantity/Artifact 和认证范围校验；
- Plan 使用 RuleBinding 显式连接 Operation/Metric/Quantity 与 Rule，不依赖 NX diagnostics；
- Plan 保存输入哈希、事实、规则、Backend 和版本快照；
- 不将黄金产品文件名/哈希写成长期业务分支，Plan 来源必须是规则和事实。

### WP3：NX Server

- 实现 HTTP v1 输入上传、Job、状态、取消、结果和 Artifact；
- 管理许可证、NX Worker、超时、崩溃和清理；
- 支持黄金产品目标 Parasolid 版本；
- capability 逐 calculator 声明认证范围；
- 完成真实 Server/Worker 部署和 Hermes 联调。

### WP4：NX C++ calculator

- `inspect_topology` 作为基础门；
- 实现追溯矩阵要求的所有 calculator；
- 只输出 Measurement、几何引用、quality、diagnostics，以及中性的 ScalarField、RenderScene 和 TopologyMap；
- 不输出失败区域、pass/fail 或截图；
- 支持取消安全点和进度；
- 输出插件/NX/calculator 版本；
- 相同输入和版本重复运行工程等价。

### WP5：Hermes Evaluation/Finding/Report

- NX 只返回 `producer_contract=measurement_only`；
- EvaluationEngine 使用 RuleBinding 和 Effective Rule Set 生成 `evaluations.json`；
- FieldEvidenceEngine 只对失败 Evaluation 筛选场数据、连接失败 Cell、生成局部 Patch 和截图；
- `materialize_evaluated_findings()` 使用 Evaluation 与 EvidenceRecord 生成精确引用；
- STEP 历史链路继续使用 Worker 证据与 `materialize_legacy_step_findings()`，不与 NX 生产链混用；
- 报告展示事实、规则、实际值、期望值、结果、区域和未解决项；
- 生产链不读取 Ground Truth。

### WP6：只读 Run Bundle

Run Bundle 是正式生产 Run 已有数据的不可变导出/集合，不含工程师答案：

```text
run-bundle/
├── bundle_manifest.json
├── input_identity.json             # hash/format，不必复制受限原文件
├── confirmed_facts.json
├── effective_rule_set.json
├── plan.json
├── backend_versions.json
├── measurements.json
├── evaluations.json
├── findings.json
├── artifacts_manifest.json
└── report.*
```

必须保存文件哈希和 schema/version。Bundle 导出不执行比较，也不根据 Ground Truth
改写结果；工程师在生产 Run 完成后人工查看这些材料。

## 7. 人工验收工作包

### WP7：工程师人工核对和签字

人工核对材料：

```text
immutable Run Bundle
approved Ground Truth version
人工验收检查表
```

工程师逐项核对：

- Plan 指标覆盖率；
- Measurement 数值是否位于逐指标批准误差内；
- Finding 是否存在漏报、误报，规则是否匹配；
- 问题区域与工程师标注是否在工程语义和空间位置上一致；
- severity、证据和报告是否完整、可解释；
- 缺失、多余或不可比较项及原因。

核对结果记录为人工验收表，可使用受控的文档或表格，不要求机器可读，不开发自动化
比较逻辑。工程师和架构负责人共同确认结论并签字：

- 工程师检查智能体结果和实际证据；
- 区分算法错误、规则错误、Ground Truth 错误和允许数值差异；
- 所有例外必须记录原因和批准人；
- 签字记录绑定输入、Ground Truth、规则、NX、插件和 Run Bundle 版本。

## 8. 人工核对准则

### 8.1 Plan 覆盖

黄金产品要求的 calculator/metric 召回率必须为 100%。多余分析项需要解释，不能用运行
全部 calculator 掩盖 PlanCompiler 选择错误。

### 8.2 Measurement

逐指标预先定义绝对误差、相对误差、分位数和无效采样率等核对口径。工程师按批准口径
核对，不要求浮点数字节级相等。

### 8.3 Finding

人工核对 rule ID、outcome、severity 和工程语义。第一条黄金产品要求工程师标注问题无未解释
漏报，不允许未经解释的高严重度误报。

### 8.4 区域

参考 bbox、参考点距离、面积比例或区域重合度进行人工判断，不比较跨 Backend Face 编号。

### 8.5 报告

检查每个 Finding 是否包含事实、Measurement、Rule、Evaluation、Evidence 和版本引用；
不做像素级报告截图比较。

## 9. 人工核对在完整链路中的位置

生产步骤：

```text
1–20  智能体完成项目、分析、Finding、Evidence 和报告
20    生产 Run 结束，结果不可变
```

研发验收步骤：

```text
21    模具工程师使用既有分析基线逐项人工核对已完成 Run，并记录差异和结论
22    模具工程师与架构负责人确认结果并签字
```

第 21 步不属于用户运行 DFM 智能体的流程，不出现在 Desktop、Agent 对话和产品 API 中，
也没有对应的软件模块或开发任务。

## 10. 测试和验收

### 10.1 生产链

- `.x_t` 上传、哈希和 NX capability；
- 确认事实、Rule Set 和 Plan；
- 所有所需 calculator 的真实 NX 执行；
- Measurement-only 契约；
- RuleBinding、Evaluation、失败 Patch、Hermes 截图、EvidenceRecord、Finding 和报告；
- 平面失败、曲面局部失败、通过不截图、错误拓扑/输入哈希和并发 Run 不串证据；
- 取消、超时、崩溃、幂等和许可证回收；
- 相同版本重复运行工程等价；
- 注塑 STEP 全量回归。

### 10.2 人工验收

- Ground Truth/工程师基线的版本和批准记录；
- Run Bundle 完整性和哈希；
- 按批准容差人工核对 Measurement；
- 人工核对 Finding、区域、缺失/多余指标、severity 和证据；
- 差异原因、处理结论、复核人和签字完整；
- 确认没有为了验收而把 Ground Truth 注入生产运行。

## 11. 第一阶段完成定义

同时满足以下条件才完成 M2.6：

1. 黄金产品事实、指标、规则、问题、区域和误差已冻结；
2. Production Task Contract 通过联合评审，Hermes/NX 双向契约测试通过；
3. 追溯矩阵完整，指标覆盖率 100%；
4. NX Server/C++ 插件完成所需真实 calculator；
5. 生产链输出完整 Run Bundle，不读取 Ground Truth；
6. 关键 Measurement 在批准误差内；
7. 工程师问题无未解释漏报，规则、区域、severity 和证据符合批准标准；
8. 同一版本重复运行工程等价；
9. 模具工程师完成逐项人工核对，所有差异都有结论；
10. 模具工程师和架构负责人签字；
11. 注塑 STEP 回归通过。

完成后可以声明“NX 黄金产品第一条真实 DFM 纵向闭环通过”，不能据此声明所有压铸
产品或所有 calculator 已具备普适生产能力。后续使用更多代表性产品扩展认证语料。

## 12. 团队分工

| 工作 | 主责 | 参与/审批 |
| --- | --- | --- |
| 黄金产品和工程结论 | 模具工程师 | 架构负责人、规则负责人 |
| 范围/追溯矩阵/验收 | 架构负责人 | 全体模块负责人 |
| Fact/Rule/Plan/Evaluation/Finding | Python DFM 领域负责人 | 架构负责人 |
| Hermes/NX Client/E2E/Run Bundle | Hermes 集成负责人 | NX Server负责人 |
| NX Server/Worker/许可证 | NX Server负责人 | 插件负责人 |
| NX C++ calculator/evidence | NX 插件负责人 | 模具工程师 |
| 人工结果核对 | 模具工程师 | 架构负责人、各模块负责人 |
| 差异修正与回归 | 对应模块负责人 | 模具工程师、架构负责人 |
| 工程签字 | 模具工程师 | 架构负责人 |

任何人都不能为了通过验收静默修改 Ground Truth 或生产结果；基线修订和例外必须由
模具工程师与架构负责人共同批准并留痕。

## 13. 相关文档

- [DFM 长期路线图](2026-07-13-dfm-hermes-agent-development-roadmap.md)
- [M2.5 多工艺与多格式架构](2026-07-22-dfm-m25-multi-process-geometry.md)
- [11661116_07 黄金产品待分析项与候选指标清单](2026-07-28-dfm-golden-product-metric-candidates-11661116-07.md)
- [NX Server/C++ 插件开发规格](2026-07-23-nx-server-plugin-development-spec.md)
- [团队架构与分工](2026-07-23-dfm-team-architecture-and-ownership.md)
- [DFM/NX Production Task Contract](../dfm-nx-task-contract.md)
