# DFM/NX Production Task Contract

> 状态：Proposed，等待 Hermes/NX 联合评审与认证。
> 数据 Schema：`1`。这是唯一生产数据契约，不提供 demo 契约兼容路径。
> 正式定义：`tools/dfm/schemas/*.schema.json`。

## 1. 边界与数据流

Hermes 负责编译计划、解析事实、冻结规则、执行规则判定、定位失败 Patch、生成截图和 Finding。NX 只负责可重复的几何计算并返回客观 Measurement 与中性几何 Artifact：

```text
Project Facts + Scope
        |
        v
Hermes Plan compiler --> Plan Operation ----------> NX Calculator
        |                  |                             |
        | RuleBinding      | required_artifacts          v
        |                  |                 Measurement + ScalarField
        | rules            |                 + RenderScene + TopologyMap
        v                  |                             |
Hermes Evaluation <--------+-----------------------------+
        |
        v
failed patches --> Hermes Evidence Renderer --> EvidenceRecord --> Finding
```

规则阈值不会发送给 NX。NX 不返回 pass/fail、severity 或 recommendation。

## 2. Plan

Plan 持久化以下互不混用的数据：

- `rules`：Hermes Evaluation 使用的有效规则快照；
- `rule_bindings`：Operation/Metric/Quantity 与 Rule 的显式确定性绑定；
- `operations`：几何计算任务；
- Project Manifest 中的 `facts` 和 `regions`：事实与区域的正式记录。

Operation 的唯一结构：

```json
{
  "operation_id": "draft.fixed_half",
  "calculator_id": "measure_draft",
  "depends_on": ["geometry.topology"],
  "metric_ids": ["dc.geometry.draft.fixed_half"],
  "required_quantities": ["draft_angle_deg"],
  "required_artifacts": ["scalar_field", "render_scene", "topology_map"],
  "arguments": {
    "pull_direction": {
      "value": [0, 0, 1],
      "unit": null,
      "source_ref": "fact:pull_direction.fixed_half"
    }
  },
  "algorithm_options": {}
}
```

`operation_id` 标识本次计划任务，`calculator_id` 标识通用计算器，`metric_ids` 标识业务指标，`required_quantities` 是任务必须返回的客观量，`required_artifacts` 是完成局部证据所需的中性几何输出。`arguments` 与 `algorithm_options` 都必须包含已解析的 `value`、`unit` 和 `source_ref`，禁止发送只有 Hermes 才能解析的 `fact_ref` 或 `region_ref`。

RuleBinding 示例：

```json
{
  "binding_id": "binding.draft.fixed_half",
  "operation_id": "draft.fixed_half",
  "metric_id": "dc.geometry.draft.fixed_half",
  "quantity_id": "draft_angle_deg",
  "rule_id": "die_casting.min_draft.fixed_half",
  "operator": ">=",
  "aggregation": "minimum"
}
```

RuleBinding 只保存在 Hermes Plan，不发送给 NX。存在生产绑定时，Evaluation 不读取 Measurement `diagnostics` 中的判定提示。

加载任务统一使用 `geometry.load` / `load_geometry`；Operation ID 不使用输入格式名称。

## 3. Region

Region 是输入版本绑定的正式记录，至少包含：

- `region_id`、`version`、`content_sha256`；
- `input_sha256` 和 `coordinate_system`；
- `mode`：`bbox`、`topology_refs` 或 `whole_model`；
- `bbox` 或 `geometry_refs`；
- `semantic_label` 与 `source_refs`。

发送给 NX 的 Region 是完整值快照，Measurement 通过 `region_refs` 回链稳定 ID。

## 4. Capability

`GET /v1/capabilities` 中每个 Calculator 必须是结构化对象，不接受字符串状态。结构包含：

- `status` 与 `contract_version=1`；
- `implementation_version`；
- `required_arguments`、`optional_arguments`、`supported_algorithm_options`、`output_quantities`、`output_artifact_kinds`；
- `supported_formats`、`supported_region_modes`、`supported_nx_versions`；
- `certification_report_sha256`。

Hermes 在提交前校验 Calculator 认证状态、参数集合、输出 Quantity、格式和 Region mode。不匹配时计划处于 blocked，而不是降级到另一套请求格式。

## 5. Measurement

Measurement 只表达客观几何结果：

```json
{
  "measurement_id": "measurement_draft_fixed_half_min",
  "operation_id": "draft.fixed_half",
  "calculator_id": "measure_draft",
  "metric_id": "dc.geometry.draft.fixed_half",
  "quantity_id": "draft_angle_deg",
  "value": 1.2,
  "unit": "degree",
  "status": "measured",
  "geometry_refs": [],
  "region_refs": ["region.fixed_half"],
  "field_refs": ["field_draft_fixed_half"],
  "method": "nx_open_draft_analysis",
  "algorithm_version": "nx-draft-1",
  "input_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "quality": {},
  "diagnostics": {}
}
```

Hermes 必须验证 Measurement 的 Operation、Calculator、Metric 和 Quantity 都属于提交任务，并验证每个 required Quantity 均已返回。`field_refs` 引用 Artifact ID，不引用文件名；要求 `scalar_field` 的 Operation 必须至少返回一个有效 field 引用。

## 6. 中性几何 Artifact

NX 不知道规则阈值，因此 NX 输出中禁止出现 `violating_samples`、`failed_patch` 或 pass/fail。三类 Artifact 的职责是：

- `scalar_field`：每个采样点的三维坐标、可选 UV、法向、客观值，以及 Cell 到网格三角形的引用；顶点采样必须提供 `mesh_vertex_ref`，三角形中心采样使用 `null`。`calculation_context` 显式保存解释该场所需的计算上下文，拔模角场必须提供归一化的 `pull_direction`，壁厚场使用空对象；Hermes 使用同一字段生成开模方向、局部曲面法向和正交侧向三个自适应证据视角；
- `render_scene`：Hermes 可直接渲染的中性三角网格；
- `topology_map`：输入 B-Rep `geometry_ref` 到场景三角形的稳定映射。

三者必须带相同 `run_id` 和 `input_sha256`。ScalarField 还必须回链 Operation、Metric、Quantity、RenderScene 和 TopologyMap。正式结构分别见 `scalar_field.schema.json`、`render_scene.schema.json` 和 `topology_map.schema.json`。

## 7. Evaluation、Evidence 与 Finding

Evaluation 显式保存：`operation_id`、`metric_id`、`measurement_ids`、`rule_id`、`rule_version`、`rule_hash`、operator、expected、actual 和 outcome。

Evaluation 失败后，Hermes 对 ScalarField 应用同一 operator/expected，连接相邻失败 Cell，生成 `evidence_geometry.json` 中的 `failed_patches`。随后 Hermes Evidence Renderer 在 RenderScene 上仅高亮这些三角形，并生成 `evidence_records.json`。EvidenceRecord 必须绑定 Run、输入哈希、Operation、Metric、Measurement、Evaluation、Geometry、Region 和图片 Artifact。

Finding 显式保存：`evaluation_ids`、`measurement_ids`、`metric_ids`、`region_refs`、`evidence_refs` 和 `rule_refs`。生产 Finding 只从独立 Evaluation 与 EvidenceRecord 生成；`evidence_refs` 保存 Evidence ID，不把一次 Run 的全部图片分配给每个 Finding。

代码保留两条明确链路，但不是两个 Schema 版本：

- STEP 历史链路：STEP Worker 自行渲染，`materialize_legacy_step_findings()` 适配旧报告；
- NX 生产链路：`EvaluationEngine` → `FieldEvidenceEngine` → `materialize_evaluated_findings()`。

## 8. 联合验收

1. Hermes 与 NX 使用 `tests/fixtures/dfm/nx/task_contract_*.json` 作为共用样例；
2. 请求、Capability、Measurement、RuleBinding、ScalarField、RenderScene、TopologyMap、EvidenceGeometry 和 EvidenceRecord 分别通过正式 JSON Schema；
3. 错误 Calculator、参数、格式、Region mode、Metric、Quantity、Artifact kind 或跨 Run/输入引用必须被拒绝；
4. 曲面局部失败能由 Hermes 生成只覆盖失败三角形的截图；通过结果不生成问题截图；
5. 同一 Measurement 经相同 Rule 快照生成相同 Evaluation、Patch 和 Finding 引用；
6. 并发项目/Run 的 Artifact 不得交叉引用；
7. Schema 冻结只能发生在 Hermes/NX 联合评审和真实 golden part E2E 通过之后。
