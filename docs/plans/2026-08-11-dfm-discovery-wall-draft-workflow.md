# DFM 两阶段发现与壁厚/拔模角工作流

本版本把注塑 DFM 的端到端范围冻结为：二维图纸观察占位、三维特征发现占位、普通区域回退、壁厚和拔模角计算、规则评价、证据和报告。NX、MTK 特征识别保持显式占位，不生成伪造结果。

## 运行顺序

当前冻结流程明确采用 Hermes 统一截图：NX/PythonOCC 生成同源 `TopologySnapshot + RenderMeshSnapshot + TopologyMap + RenderScene + ScalarField`，Hermes 完成规则评价、FailedPatch 聚合和三视角证据渲染。Hermes 不重新加载 CAD 文件寻找 Backend 的 Face；高亮只使用绑定到该 RenderMeshSnapshot 的 TriangleRef。

```text
STEP / Parasolid / drawing 登记
  → 二维 Observation Provider（当前占位）
  → Discovery 前置事实门
       process, model_units
  → 通用三维 Discovery（当前 ordinary_part 回退）
  → 工艺特征识别（NX/MTK 占位，不生成伪特征）
  → DiscoverySnapshot
  → Analysis 前置事实门
       material, pull_dir
  → AnalysisPlan
  → wall_thickness / draft_angle ObjectiveTask
  → Measurement + ScalarField + RenderScene v2 + TopologyMap v2
  → Hermes Evaluation
  → FailedPatch v2
  → Hermes Evidence Renderer（三视角）
  → EvidenceRecord / FindingRecord / Report
```

Discovery 前置事实决定“使用哪条识别路径”；Analysis 前置事实决定“如何计算和评价”。图纸提取到的高置信度事实可以直接进入 `FactRecord`，冲突或缺失时才生成澄清。特征低置信度澄清与事实澄清使用同一项目澄清机制，不要求用户经历两个独立 UI 流程。

澄清不是全部放在特征识别之后。当前可执行的普通区域识别依赖 `model_units`，工艺语义依赖 `process`，所以二者必须在冻结 Discovery Snapshot 前确认。识别器在特征目录中声明 `required_fact_names`；将来启用依赖方向的倒扣/滑块识别器时，`pull_dir` 会自动升级为该识别器执行前的 Discovery 事实。当前这些识别器仍是占位，因此 `pull_dir` 保持在 Analysis 门，不提前打扰用户。

## 当前事实清单

事实来源必须可追溯到用户、图纸观察或明确元数据，禁止模型猜测。

| fact | 阶段 | 用途 |
| --- | --- | --- |
| `process` | discovery | 选择注塑/压铸语义识别和规则 Scope |
| `model_units` | discovery | 几何尺寸、采样和容差归一化；当前计算要求 `mm` |
| `material` | analysis | 选择壁厚规则材料 Profile；当前 ABS Scope 为 `min_wall_mm=1.2` |
| `pull_dir` | analysis | 拔模角计算和后续倒扣/侧向特征识别；当前默认规则为 `min_draft_deg=1.0` |

注塑配置位于 `tools/dfm/scopes/injection/wall_draft.json`，特征识别目录位于 `tools/dfm/scopes/injection/feature_catalog.json`。

## 特征和普通区域

当前没有可执行的螺柱、加强筋、倒扣识别器，因此 Discovery 为每个活动几何输入建立一个覆盖全模型的：

- `FeatureRecord.kind = ordinary_part`；
- `RegionRecord.mode = whole_model`、`role = ordinary`；
- `recognizer = ordinary-region-fallback`。

特征目录的 `placeholder_policy` 明确规定 `treat_as_ordinary`：NX/MTK 占位模块不得伪造螺柱、筋位或倒扣；系统用覆盖全模型的普通区域执行壁厚和拔模角。占位特征的规则 Profile 通过 `fallback_to = ordinary.wall_draft` 表明未来即使先获得特征区域、但专用阈值尚未验证，也按普通区域规则评价并保留 Feature/Region 身份。

壁厚和拔模角 Operation、RuleBinding、Measurement、ScalarField、Evaluation、Evidence、Finding 均引用该 Feature/Region。未来 NX 或 MTK 识别出 `screw_boss`、`rib` 等特征时，只需替换 Discovery Snapshot 中的区域集合，后处理契约不变。

## 关键契约

```text
ProjectManifest
  inputs / facts / observations / features / regions / fusion_links
  discovery_snapshots / plans / runs / findings / artifacts

DiscoverySnapshotRecord
  input_hashes + feature_refs + region_refs + provider_versions
  confirmed_fact_refs + content_sha256

PlanOperation
  required_fact_names + feature_refs + region_refs

RuleBinding
  required_fact_names + metric/quantity/rule + feature_refs + region_refs

ObjectiveTaskRequest (schema 4)
  run/input/process/scope + regions + operations

MeasurementRecord
  operation/metric/quantity + feature_refs + region_refs
  geometry_refs + field_refs + input_sha256
```

`material` 是壁厚规则 Profile 的依赖，不是壁厚几何算法的输入，因此记录在 `RuleBinding.required_fact_names`；`model_units` 才记录在壁厚 `PlanOperation.required_fact_names`。这样材料变化只会重建壁厚评价闭包，缓存中的客观几何结果仍可复用。拔模角计算依赖 `pull_dir` 和 `model_units`，阈值 `min_draft_deg` 由版本化规则库提供。

真实特征接入后，ordinary 不再等于 whole model：已被壁厚/拔模角特征绑定接管的 Face 写入普通 Region 的 `excluded_geometry_refs`，模式变为 `topology_complement`。Plan Compiler 对每个目标 Region 分别展开壁厚和拔模角 Operation；PythonOCC 与 NX 都从 ObjectiveTask 顶层 `regions` 解析相同选择器。当前没有真实特征时，ordinary 仍是 whole-model fallback，保持 Demo 可执行。

Evidence 通过 `Measurement.field_refs` 找到 ScalarField，再通过失败 sample/cell 的 `geometry_ref` 和 `triangle_ref` 回到 `RenderScene`，因此普通区域回退也能生成精确高亮；不会用固定红点或跨项目的面索引。

## 后端边界

- PythonOCC：当前 STEP Demo 的真实 Objective Calculator。
- NX：`NXFeatureRecognitionProvider` 和生产 Analyzer 的契约占位；未实现能力明确返回 `not_implemented`。
- MTK：`MTKFeatureRecognitionProvider` 的契约占位；未安装或未实现时不生成 FeatureRecord。
- Hermes：统一编译计划、评价规则、生成证据和报告，后端不得携带规则阈值或 pass/fail 结论。
