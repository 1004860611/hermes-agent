# DFM/NX Production Task Contract

> 状态：Proposed，等待 Hermes/NX 联合评审与认证。
> 数据 Schema：`1`。这是唯一生产数据契约，不提供 demo 契约兼容路径。
> 正式定义：`tools/dfm/schemas/*.schema.json`。

## 1. 边界与数据流

Hermes 负责编译计划、解析事实、冻结规则、执行规则判定和生成 Finding。NX 只负责可重复的几何计算并返回 Measurement：

```text
Project Facts + Scope
        |
        v
Hermes Plan compiler --> Plan Operation --> NX Calculator
        |                                     |
        | rules                               v
        +---------------------------- Measurement
                                              |
                                              v
                                  Hermes Evaluation --> Finding
```

规则阈值不会发送给 NX。NX 不返回 pass/fail、severity 或 recommendation。

## 2. Plan

Plan 持久化以下互不混用的数据：

- `rules`：Hermes Evaluation 使用的有效规则快照；
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

`operation_id` 标识本次计划任务，`calculator_id` 标识通用计算器，`metric_ids` 标识业务指标，`required_quantities` 是任务必须返回的客观量。`arguments` 与 `algorithm_options` 都必须包含已解析的 `value`、`unit` 和 `source_ref`，禁止发送只有 Hermes 才能解析的 `fact_ref` 或 `region_ref`。

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
- `required_arguments`、`optional_arguments`、`supported_algorithm_options`、`output_quantities`；
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
  "method": "nx_open_draft_analysis",
  "algorithm_version": "nx-draft-1",
  "input_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "quality": {},
  "diagnostics": {}
}
```

Hermes 必须验证 Measurement 的 Operation、Calculator、Metric 和 Quantity 都属于提交任务，并验证每个 required Quantity 均已返回。

## 6. Evaluation 与 Finding

Evaluation 显式保存：`operation_id`、`metric_id`、`measurement_ids`、`rule_id`、`rule_version`、`rule_hash`、operator、expected、actual 和 outcome。

Finding 显式保存：`evaluation_ids`、`measurement_ids`、`metric_ids`、`region_refs`、`evidence_refs` 和 `rule_refs`。Finding 只从独立的 Evaluation artifact 生成，不从 Measurement 推断或读取历史内嵌判定。

## 7. 联合验收

1. Hermes 与 NX 使用 `tests/fixtures/dfm/nx/task_contract_*.json` 作为共用样例；
2. 请求、Capability、Measurement 分别通过正式 JSON Schema；
3. 错误 Calculator、参数、格式、Region mode、Metric 或 Quantity 必须被拒绝；
4. 同一 Measurement 经相同 Rule 快照生成相同 Evaluation 和 Finding 引用；
5. Schema 冻结只能发生在 Hermes/NX 联合评审和真实 golden part E2E 通过之后。
