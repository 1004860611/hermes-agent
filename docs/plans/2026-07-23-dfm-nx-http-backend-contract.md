# DFM NX HTTP Backend 契约

> 数据对象以 [DFM/NX Production Task Contract](../dfm-nx-task-contract.md) 和
> `tools/dfm/schemas/*.schema.json` 为准。HTTP 路径版本为 `/v1`，请求数据 Schema 唯一为 `1`。

## 1. 边界

Hermes 只通过 `HttpNXBackendClient` 访问独立 NX Server，不提供本地 NX fallback。Server 负责认证、输入上传、Job 队列、许可证、Worker、取消和 Artifact；C++ 插件只执行 capability 声明的 Calculator。NX 只返回 Measurement，Hermes 负责 Rule、Evaluation 和 Finding。

## 2. API

```text
GET  /v1/capabilities
POST /v1/inputs
PUT  /v1/inputs/{input_id}/content
POST /v1/jobs
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/cancel
GET  /v1/jobs/{job_id}/result
GET  /v1/jobs/{job_id}/artifacts/{artifact_id}
```

输入先登记，再流式上传，最后由 Job 使用 `input_id + sha256 + format_id` 引用。Server 必须限制大小、校验 SHA-256，并禁止客户端传入 Server 本地路径。

## 3. Job 请求

```json
{
  "schema_version": 1,
  "run_id": "run_0123456789abcdef",
  "process": "die_casting",
  "scope_id": "die_casting.golden-product",
  "scope_version": "1.0.0",
  "input": {
    "input_id": "nxinput_01abc",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "format_id": "parasolid_xt"
  },
  "operations": [
    {
      "operation_id": "geometry.topology",
      "calculator_id": "inspect_topology",
      "depends_on": ["geometry.load"],
      "metric_ids": ["geometry.model"],
      "required_quantities": ["valid_brep"],
      "arguments": {},
      "algorithm_options": {}
    }
  ]
}
```

请求不含 Rule 阈值。每个参数必须是已解析值并带 `source_ref`。Server 依据结构化 capability 校验 Calculator、参数、输出 Quantity、格式、Region mode 和 Schema；任何不匹配都拒绝，不尝试另一种请求形状。

相同授权域中的相同 `run_id + input.sha256 + schema_version` 重复提交必须幂等。

## 4. 状态与取消

```text
queued -> starting -> running -> succeeded
                           |-> failed
queued/starting/running -> cancelling -> cancelled
```

进度不得倒退。取消需设置协作式 cancellation flag，在 Calculator 安全点退出；超过 grace period 后终止该 Job 的 Worker 进程并回收许可证。

## 5. Result 与 Artifact

成功 Result 至少且只能包含一个 `kind=measurements` Artifact。每个 Artifact 提供 `artifact_id`、单层安全 `filename`、`media_type`、`sha256` 和 `size_bytes`。Hermes 下载后重新校验大小和哈希。

Measurement artifact 必须满足 `measurement.schema.json`，且 `producer_contract=measurement_only`。NX 不得返回生产 Evaluation 或 Finding。

## 6. 错误

稳定错误至少包括：`schema_invalid`、`unsupported_calculator`、`unsupported_argument`、`unsupported_quantity`、`unsupported_region_mode`、`input_hash_mismatch`、`license_unavailable`、`nx_execution_failed`、`cancelled`。

## 7. 验收

- 共用 `tests/fixtures/dfm/nx/task_contract_*.json`；
- capability、请求和 measurement 通过正式 Schema；
- 上传、幂等、轮询、取消、崩溃恢复、Artifact 安全和哈希校验有真实 Server E2E；
- golden part 的 required Quantities 全部返回并能由 Hermes 生成 Evaluation/Finding；
- STEP/OpenCascade 回归不受 NX 服务状态影响。
