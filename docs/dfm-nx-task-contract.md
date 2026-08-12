# DFM/NX Production Task Contract

> 状态：Hermes freeze candidate；真实 NX 联合评审、配对 Golden Model 和 Calculator 认证仍是生产发布门。
> Objective Task/Result Schema：`2`。Measurement/ScalarField/RenderScene/TopologyMap 仍各自使用 Schema `1`；这是对象类型的版本差异，不是 V1/V2 双轨。
> 正式定义：`tools/dfm/schemas/*.schema.json`。

## 1. 边界与数据流

### 1.0 Hermes 统一截图与不可变几何快照

PythonOCC 与 NX 都只返回客观几何结果；正式证据图片一律由 Hermes Renderer 从 Backend 返回的中性 `RenderScene` 生成，Hermes 不重新打开 STEP/Parasolid，也不使用另一个 CAD 内核重新寻找 Face。

每次 Backend 加载模型并编号拓扑时，必须在 `TopologyMap.topology_snapshot` 中记录 `topology_snapshot_id`、输入 SHA256、Backend/Loader/Indexer 版本、实体数量和拓扑内容哈希。正式 `GeometryRef` 同时携带 `topology_snapshot_id + entity_id + input_sha256`；`index` 只作为该快照内的可读辅助编号，不得跨 Backend 或跨快照比较。

每次离散化必须在 `RenderScene.render_mesh_snapshot` 中记录 `render_mesh_snapshot_id`、所属 `topology_snapshot_id`、网格参数、三角形数量和网格内容哈希。所有 Primitive、VertexRef 和 TriangleRef 必须携带同一个 `render_mesh_snapshot_id`。重新三角化即产生新的 Mesh Snapshot，旧 TriangleRef 不得复用。

可追溯链路固定为：

```text
Input SHA256
  → TopologySnapshot
  → GeometryRef(entity_id)
  → TopologyMap
  → RenderMeshSnapshot
  → TriangleRef
  → ScalarField Sample/Cell
  → Measurement
  → Hermes Evaluation
  → FailedPatch
  → Hermes Evidence Renderer
  → EvidenceRecord
  → Finding / Report
```

Hermes 在接收 Objective Result 和生成证据前都要校验上述关系。任何输入、Run、Topology Snapshot、Mesh Snapshot、Scene、Map 或 Field 不一致，都必须以 `objective_result_invalid`、`evidence_field_invalid` 或 `evidence_snapshot_mismatch` 失败；禁止降级为按 Face 序号猜测位置后继续截图。

Hermes 负责编译两阶段计划、融合 Observation/Feature/Region、解析事实、冻结规则、执行规则判定、定位失败 Patch、生成截图和 Finding。NX 只负责可重复的三维特征发现和几何计算，并返回客观 Feature/Region、Measurement 与中性几何 Artifact：

```text
Inputs -----------------------> DiscoveryPlan
  |                                 |
  | drawing                         | model
  v                                 v
Observation Provider       NX 3D Feature Recognizer
  |                         FeatureSet + RegionSet
  +-------------------> Fusion / Clarification
                                  |
                                  v
                       Immutable Discovery Snapshot
                                  |
                       RuleSelector + AnalysisPlan
                                  |
                                  v
                       NX Objective Calculators
                       Measurement + ScalarField
                       + RenderScene v2 + TopologyMap v2
                                  |
                                  v
                    Hermes Evaluation / FailedPatch v2
                                  |
                                  v
                    Hermes Renderer --> EvidenceRecord --> Finding / Report
```

规则阈值不会发送给 NX。NX 不返回 pass/fail、severity 或 recommendation。

### 1.1 输入格式与 Backend 选择

- `ObjectiveTaskRequest.input_format` 支持 `step` 与 `parasolid_xt`。
- PythonOCC 只承载 STEP demo；NX production 同时承载 STEP 与 Parasolid，并在 NX 内使用两个 loader 规范化为相同的 B-Rep 计算输入。
- 输入格式不进入 `operation_id`、`metric_id` 或 `calculator_id`。同一个 `measure_draft` 或 `measure_thickness` Calculator 对两种格式保持相同的参数、Quantity 和 Artifact 语义。
- NX Capability 必须在每个 Calculator 的 `supported_formats` 中分别认证 `step` 和 `parasolid_xt`；没有对应格式认证时，Hermes 在提交前将计划置为 blocked。
- 一旦计划选择 NX production，Backend 不可用、格式不受支持或计算失败都必须明确失败，不得自动降级到 PythonOCC。

## 2. 两阶段 Plan

### 2.1 DiscoveryPlan

`phase=discovery`，只执行不依赖 DFM 阈值的客观发现：模型导入、拓扑索引、网格、三维
特征识别，以及可选的二维 Observation Provider。三维 `recognize_molding_features`
Operation 必须返回 `feature_set` 和 `region_set`；不得返回 pass/fail。

Feature/Region/Observation/FusionLink 按输入哈希和识别器版本固化为 Discovery Snapshot。
快照冻结后不原地改写；输入、Recognizer 版本或人工确认变化时创建新快照。

### 2.2 AnalysisPlan

`phase=analysis`，必须引用所使用的 Discovery Snapshot。Plan 持久化以下互不混用的数据：

- `rules`：Hermes Evaluation 使用的有效规则快照；
- `rule_bindings`：Operation/Metric/Quantity 与 Rule 的显式确定性绑定；
- `operations`：几何计算任务；
- Project Manifest 中的 `facts`、`features` 和 `regions`：事实、三维特征与区域的正式记录；
- `discovery_snapshot_refs`：编译当前规则和区域任务所依据的不可变发现版本。

Operation 的唯一结构（Schema 4）现在同时引用 ObjectiveTask 顶层冻结的 `regions`；后端不得仅凭无法解析的 Region ID 猜测计算范围：

```json
{
  "operation_id": "draft.fixed_half",
  "calculator_id": "measure_draft",
  "depends_on": ["geometry.topology"],
  "metric_ids": ["dc.geometry.draft.fixed_half"],
  "required_quantities": ["draft_angle_deg"],
  "required_artifacts": ["scalar_field", "render_scene", "topology_map"],
  "required_fact_names": ["pull_dir", "model_units"],
  "feature_refs": ["feature.screw_boss.003"],
  "region_refs": ["region.screw_boss.003.outer_wall"],
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
  "aggregation": "minimum",
  "required_fact_names": [],
  "feature_refs": ["feature.screw_boss.003"],
  "region_refs": ["region.screw_boss.003.outer_wall"]
}
```

RuleBinding 只保存在 Hermes Plan，不发送给 NX。存在生产绑定时，Evaluation 不读取 Measurement `diagnostics` 中的判定提示。

`required_fact_names` 按真正消费者分开记录：`model_units`、`pull_dir` 等客观计算输入属于 Operation；`material` 等只用于选择阈值的事实属于 RuleBinding。修改规则事实不得改变发送给 NX 的 ObjectiveTask。

区域化任务采用以下不重叠语义：真实特征区域必须使用 `mode=topology_refs` 并携带当前输入的稳定 Face `geometry_refs`；普通区域使用 `mode=topology_complement`，其 `excluded_geometry_refs` 是已经被适用特征规则接管的 Face。未识别出真实特征时，普通区域保持 `mode=whole_model`。AnalysisPlan 按 `Feature × Region × Metric` 生成独立 Operation/RuleBinding，重叠特征对同一指标声明相同 Face 时必须阻塞，不能重复评价。

壁厚只限制采样起点属于目标 Region，射线仍与完整实体求交；拔模角只在目标 Region 的表面采样。这样螺柱壁仍可测到对侧壁，同时不会再次落入普通区域 Finding。

加载任务统一使用 `geometry.load` / `load_geometry`；Operation ID 不使用输入格式名称。

## 3. Observation、Feature、Region 与 FusionLink

### 3.1 Observation

二维 PDF/OCR/Vision 输出必须先保存为 Observation，包含输入、页码/视图/bbox/原文来源、
规范化候选值、单位、置信度和状态。`candidate`、`conflict` 或
`needs_confirmation` Observation 不能直接参与 RuleSelector。

M2.6 允许 Drawing Provider 的具体实现保持 `not_implemented`，但接口和占位流程固定为：

```text
render_pages
→ extract_native_text_or_ocr
→ detect_views_and_callouts
→ normalize_candidates
→ emit Observation[]
```

### 3.2 Feature

三维 Feature 是输入版本绑定的确定性发现，至少包含：

- `feature_id`、`kind`、`input_sha256`、`status` 和 `confidence`；
- `region_refs`：特征整体及角色区域，例如 `outer_wall`、`inner_wall`、`root`；
- `properties`：高度、半径、轴向等客观识别属性，不保存规则判定；
- `relationships`：`attached_to`、`reinforced_by`、`adjacent_to` 等可审计关系；
- `recognizer` 与 `recognizer_version`。

M2.6 首批实际识别 `main_wall`、`screw_boss`、`rib`、`boss`、`fillet`。NX production 对
STEP/Parasolid 必须输出相同语义；MTK/PythonOCC Provider 也只能转换到此契约，不得把
SDK 内部对象号当成跨 Run 稳定 ID。

### 3.3 Region

Region 是输入版本绑定的正式记录，至少包含：

- `region_id`、`version`、`content_sha256`；
- `input_sha256` 和 `coordinate_system`；
- `mode`：`bbox`、`topology_refs` 或 `whole_model`；
- `bbox` 或 `geometry_refs`；
- `semantic_label`、`role`、`feature_refs` 与 `source_refs`。

发送给 NX 的 Region 是完整值快照，Measurement 通过 `region_refs` 回链稳定 ID。

### 3.4 FusionLink

FusionLink 显式连接 Observation、Feature 和 Region，并保存匹配方法、置信度、状态与诊断。
一对多、低置信度或二维/三维冲突必须保持 `ambiguous` 并触发澄清，不能强制绑定。

## 4. Capability

`GET /v1/capabilities` 中每个 Calculator 必须是结构化对象，不接受字符串状态。结构包含：

- `status` 与 `contract_version=2`；
- `implementation_version`；
- `required_arguments`、`optional_arguments`、`supported_algorithm_options`、`output_quantities`、`output_artifact_kinds`；
- `supported_formats`、`supported_region_modes`、`supported_nx_versions`；
- `certification_report_sha256`。

Hermes 在提交前校验 Calculator 认证状态、参数集合、输出 Quantity、格式和 Region mode。不匹配时计划处于 blocked，而不是改写请求格式或降级到另一个 Backend。某 Calculator 支持 `parasolid_xt` 不代表它自动支持 `step`，反之亦然。

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
  "feature_refs": ["feature.screw_boss.003"],
  "region_refs": ["region.fixed_half"],
  "field_refs": ["field_draft_fixed_half"],
  "method": "nx_open_draft_analysis",
  "algorithm_version": "nx-draft-1",
  "input_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "quality": {},
  "diagnostics": {}
}
```

Hermes 必须验证 Measurement 的 Operation、Calculator、Metric 和 Quantity 都属于提交任务，并验证每个 required Quantity 均已返回。特征区域任务还必须验证 `feature_refs`、`region_refs` 属于 AnalysisPlan 引用的 Discovery Snapshot。`field_refs` 引用 Artifact ID，不引用文件名；要求 `scalar_field` 的 Operation 必须至少返回一个有效 field 引用。

M2.6 特征规则至少使用以下客观 Quantity：

- `wall_thickness_mm`：主壁、螺柱、筋、Boss 区域的局部厚度；
- `draft_angle_deg`：相对确认开模方向的局部拔模角；
- `fillet_radius_mm`：特征根部或指定圆角 Region 的真实圆角半径。

比例规则由 Hermes 使用多个 Measurement 计算，不让 NX 读取规则阈值。例如螺柱壁厚比由
螺柱 `outer_wall` 厚度和相邻 `main_wall` 名义厚度共同组成 Evaluation 输入。

## 6. 中性几何 Artifact

NX 不知道规则阈值，因此 NX 输出中禁止出现 `violating_samples`、`failed_patch` 或 pass/fail。Discovery 阶段新增两类客观 Artifact：

- `feature_set`：符合 `feature.schema.json` 的三维 Feature 列表；
- `region_set`：符合 `region.schema.json` 的特征区域列表。

Analysis 阶段三类中性几何 Artifact 的职责是：

- `scalar_field`：每个采样点的三维坐标、可选 UV、法向、客观值，以及 Cell 到网格三角形的引用；顶点采样必须提供 `mesh_vertex_ref`，三角形中心采样使用 `null`。`calculation_context` 显式保存解释该场所需的计算上下文，拔模角场必须提供归一化的 `pull_direction`，壁厚场使用空对象；Hermes 使用同一字段生成开模方向、局部曲面法向和正交侧向三个自适应证据视角；
- `render_scene`：Hermes 可直接渲染的中性三角网格；
- `topology_map`：输入 B-Rep `geometry_ref` 到场景三角形的稳定映射。

三者必须带相同 `run_id` 和 `input_sha256`。ScalarField 还必须回链 Operation、Metric、Quantity、RenderScene 和 TopologyMap。正式结构分别见 `scalar_field.schema.json`、`render_scene.schema.json` 和 `topology_map.schema.json`。

## 7. Evaluation、Evidence 与 Finding

Evaluation 显式保存：`operation_id`、`metric_id`、`measurement_ids`、`feature_refs`、`region_refs`、`rule_id`、`rule_version`、`rule_hash`、operator、expected、actual 和 outcome。

Evaluation 失败后，Hermes 对 ScalarField 应用同一 operator/expected，并先与目标 FeatureRegion 求交，再连接相邻失败 Cell，生成 `evidence_geometry.json` 中的 `failed_patches`。随后 Hermes Evidence Renderer 在 RenderScene 上仅高亮这些三角形，并生成 `evidence_records.json`。EvidenceRecord 必须绑定 Run、输入哈希、Operation、Metric、Measurement、Evaluation、Feature、Region、Geometry 和图片 Artifact。

Finding 显式保存：`evaluation_ids`、`measurement_ids`、`metric_ids`、`feature_refs`、`region_refs`、`evidence_refs` 和 `rule_refs`。生产 Finding 只从独立 Evaluation 与 EvidenceRecord 生成；`evidence_refs` 保存 Evidence ID，不把一次 Run 的全部图片分配给每个 Finding。

PythonOCC demo 与 NX production 只在输入适配和客观几何实现上不同；MTK 与 NX Feature Recognizer 当前是显式占位，不执行也不生成伪特征，系统以 ordinary 全模型区域完成当前闭环。未来启用任一 Recognizer 后，仍统一输出 Feature/Region，并让 PythonOCC/NX 的 ObjectiveResultManifest、Measurement、ScalarField、RenderScene、TopologyMap 进入同一 `RuleSelector` → `EvaluationEngine` → `FieldEvidenceEngine` → `materialize_evaluated_findings()` → 报告装配。截图策略、规则和 Finding 不进入任何几何 Backend。

## 8. 联合验收

1. Hermes 与 NX 使用 `tests/fixtures/dfm/nx/task_contract_*.json` 作为共用样例；
2. Observation、Feature、Region、FusionLink、请求、Capability、Measurement、RuleBinding、ScalarField、RenderScene、TopologyMap、EvidenceGeometry 和 EvidenceRecord 分别通过正式 JSON Schema；
3. 错误 Calculator、参数、格式、Region mode、Metric、Quantity、Artifact kind 或跨 Run/输入引用必须被拒绝；
4. 曲面局部失败能由 Hermes 生成只覆盖失败三角形的截图；通过结果不生成问题截图；
5. 同一 Measurement 经相同 Rule 快照生成相同 Evaluation、Patch 和 Finding 引用；
6. 并发项目/Run 的 Artifact 不得交叉引用；
7. 同一 CAD 源导出的 STEP 与 Parasolid golden model 都必须真实进入 NX，并按批准的数值容差和问题区域语义通过壁厚、拔模角验收；不要求两个格式的采样点逐点完全相同；
8. NX production 失败时必须明确失败，验收不得接受自动降级产生的 PythonOCC 结果；
9. Schema 冻结只能发生在 Hermes/NX 联合评审和真实 golden part E2E 通过之后。
10. AnalysisPlan 引用过期或其它输入的 Discovery Snapshot、Feature 或 Region 必须被拒绝；
11. 螺柱、筋等真实 Feature 的区域化壁厚/拔模角和根部 R 角能从 RuleBinding 一直追溯到截图，低置信度特征不自动产生正式 Finding。
