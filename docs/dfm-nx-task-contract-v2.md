# DFM/NX Task Contract v2

状态：M2.6 实施冻结版

本文定义 DFM 业务指标如何转换为带参数的 NX Calculator 任务，以及 Measurement 如何回链
到该任务。v2 扩展现有请求 v1，不改变已持久化的 STEP 或 NX topology v1 Plan。

## 1. 稳定标识

| 标识 | 含义 | 示例 | Owner |
| --- | --- | --- | --- |
| Rule ID | 确定性工程判据 | `die_casting.min_draft.fixed_half` | 规则/领域负责人 |
| Metric ID | 业务上要回答的问题 | `dc.geometry.draft.fixed_half` | 领域负责人 |
| Calculator ID | Backend 无关的通用算法能力 | `measure_draft` | Geometry 契约负责人 |
| Operation ID | 当前 Plan 中的一次任务实例 | `draft.fixed_half` | Plan Compiler |
| Measurement ID | 当前 Run 中的一条结果记录 | `measurement_draft_fixed_half_min` | Backend Runtime |
| Region ID | 版本化项目区域 | `region.fixed_half` | Project Fact/Region |

Calculator ID 必须通用且稳定。方向、区域、工艺和黄金产品身份不能编码到 Calculator ID，
也不能形成产品专用代码分支。

M2.6 的正式 Calculator ID 为：

```text
inspect_topology
measure_draft
measure_wall_thickness
inspect_undercut
```

`measure_draft_by_direction` 和 `detect_undercut_by_direction` 只作为自然语言描述，不是
Calculator ID。

## 2. Plan Operation v2

v2 Operation 同时标识通用 Calculator、它服务的业务 Metric 和当前任务的局部参数：

```json
{
  "operation_id": "draft.fixed_half",
  "calculator_id": "measure_draft",
  "depends_on": ["geometry.topology"],
  "metric_refs": ["dc.geometry.draft.fixed_half"],
  "arguments": {
    "pull_direction": {"fact_ref": "pull_direction.fixed_half"},
    "region": {"region_ref": "region.fixed_half"}
  }
}
```

约束：

- `operation_id` 在当前 Plan 内唯一；
- `calculator_id` 必须匹配 Backend capability 声明的 Calculator；
- `metric_refs` 保存稳定的业务 Metric ID；
- `arguments` 只能保存字面值或指向不可变 Plan 快照中事实/区域的版本化引用；
- 规则阈值不作为 Calculator 参数，v1 兼容期保留的历史参数除外；
- 不同方向使用不同 Operation，但复用同一个通用 Calculator ID。

因此，六方向拔模使用六个 Operation ID 和六组方向/区域参数，但全部使用
`calculator_id=measure_draft`。

## 3. Capability v2

v1 Operation 继续接受历史字符串状态：

```json
{"inspect_topology": "certified"}
```

v2 业务任务必须匹配结构化 Calculator Definition：

```json
{
  "measure_draft": {
    "status": "certified",
    "contract_version": 2,
    "implementation_version": "nx-draft-v1",
    "required_arguments": ["pull_direction", "region"],
    "optional_arguments": ["excluded_regions"],
    "output_quantities": ["draft_angle_deg", "below_threshold_area_mm2"],
    "certification_scope": {
      "supports_region_filter": true,
      "supports_directional_analysis": true
    }
  }
}
```

当 Calculator 不是 `certified`、契约版本过低、缺少必需参数，或 Plan 提供了认证范围外的
参数时，Hermes 必须在提交 Job 前阻塞执行。

## 4. Measurement v2 回链

Measurement 只保存客观结果，不包含 Rule outcome 或 severity。v2 增加任务回链字段，
用于区分多个方向任务产生的同名测量量：

```json
{
  "measurement_id": "measurement_draft_fixed_half_min",
  "check_id": "draft.fixed_half",
  "operation_ref": "draft.fixed_half",
  "calculator_id": "measure_draft",
  "metric_id": "dc.geometry.draft.fixed_half",
  "metric": "draft_angle_deg",
  "value": 1.2,
  "unit": "degree",
  "status": "measured",
  "geometry_refs": [],
  "method": "nx_open_draft_analysis",
  "algorithm_version": "nx-draft-v1",
  "input_sha256": "64位小写十六进制",
  "quality": {},
  "diagnostics": {}
}
```

v2 NX 结果必须满足：

- `operation_ref` 引用本次提交 Plan 中的 Operation；
- `calculator_id` 与该 Operation 的 Calculator ID 相同；
- `metric_id` 属于该 Operation 的 `metric_refs`；
- `metric` 表示具体测量量，不代替业务 Metric ID；
- `check_id` 为兼容 Measurement v1 保留，在 v2 中必须等于 `operation_ref`；
- 几何引用和 Evidence 对不可变输入及 producer 版本保持稳定。

## 5. 兼容策略

| 生产方/消费方 | 契约 | 行为 |
| --- | --- | --- |
| 现有 STEP Plan | Plan/Request v1 | 不变 |
| 现有 NX topology Plan | Request v1 | 不变；`load_step` 表示加载当前几何输入 |
| M2.6 方向/区域任务 | Request v2 | 使用 `calculator_id`、`metric_refs` 和任务级 `arguments` |
| NX Server | Request v1/v2 | v2 迁移期必须同时接受两版请求 |

当任一 Plan Operation 包含 `metric_refs` 或 `arguments` 时，Hermes 选择请求 v2；否则继续
发送请求 v1。历史 `load_step` 的重命名需要新的请求 Schema，不属于 M2.6 范围。

## 6. 契约验收

同时满足以下条件，契约门才通过：

1. Python 能往返解析 v1/v2 Plan Operation；
2. v1 序列化结果保持不变；
3. Hermes 拒绝未认证或参数不兼容的 Calculator Definition；
4. Hermes 使用 `calculator_id`、`metric_refs` 和 `arguments` 发送 v2 Operation；
5. NX Server/C++ 解析同一组 fixture，并返回正确回链的 v2 Measurement；
6. Evaluation 能通过 Operation ID 和 Metric ID 将 Measurement 解析到批准 Rule；
7. Hermes 与 NX 两侧均保留 v1 兼容测试。
