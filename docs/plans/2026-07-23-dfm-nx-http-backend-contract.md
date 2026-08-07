# DFM NX HTTP Backend 契约

> 数据对象以 [DFM/NX Production Task Contract](../dfm-nx-task-contract.md) 和
> `tools/dfm/schemas/*.schema.json` 为准。HTTP 路径版本仍为 `/v1`，Objective Task/Result Schema 唯一为 `2`。

## 1. 边界

Hermes 只通过 `HttpNXBackendClient` 访问独立 NX Server，不提供本地 NX fallback。NX production 必须同时接收 STEP（`.step`/`.stp`）和 Parasolid（`.x_t`），在 NX 内分别加载并规范化为同一 B-Rep 计算输入。Server 负责认证、输入上传、Job 队列、许可证、Worker、取消和 Artifact；C++ 插件只执行 capability 声明的 Calculator。NX 返回 Measurement 与中性场/场景/拓扑映射，Hermes 负责 Rule、Evaluation、局部截图和 Finding。

PythonOCC 仅用于 STEP demo。用户或计划选择 NX production 后，NX 不可用、格式不受支持或计算失败都必须明确失败，不得自动转交 PythonOCC 继续生成看似成功的生产结果。

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

`format_id` 的正式取值为 `step | parasolid_xt`。文件扩展名只用于上传入口的初步识别，最终格式由登记信息、内容校验和 capability 共同确认。

## 3. Job 请求

```json
{
  "schema_version": 2,
  "input": {
    "input_id": "nxinput_01abc",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "format_id": "parasolid_xt"
  },
  "task": {
    "schema_version": 2,
    "run_id": "run_0123456789abcdef",
    "input_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "input_format": "parasolid_xt",
    "process": "injection",
    "scope_id": "injection.wall-draft",
    "scope_version": "2.0.0",
    "operations": []
  }
}
```

上例使用 Parasolid；提交 STEP 时，`input.format_id` 与 `task.input_format` 都必须改为 `step`。HTTP envelope 中的 `input.sha256`/`format_id` 必须分别等于 Task 中的 `input_sha256`/`input_format`，否则 Server 在创建 Job 前拒绝请求。输入格式只选择 NX loader，不改变 Operation、Metric、Quantity 或 Calculator ID。

请求不含 Rule 阈值。每个参数必须是已解析值并带 `source_ref`。Server 依据结构化 capability 校验 Calculator、参数、输出 Quantity、Artifact kind、格式、Region mode 和 Schema；任何不匹配都拒绝，不尝试另一种请求形状。

Capability 必须对每个 Calculator 分别声明并认证 `step` 与 `parasolid_xt`。只认证其中一种格式时，Hermes 只能为该格式提交任务，不能把“Calculator 可用”等同于“两种格式均已认证”。

相同授权域中的相同 `run_id + input.sha256 + schema_version` 重复提交必须幂等。

## 4. 状态与取消

```text
queued -> starting -> running -> succeeded
                           |-> failed
queued/starting/running -> cancelling -> cancelled
```

进度不得倒退。取消需设置协作式 cancellation flag，在 Calculator 安全点退出；超过 grace period 后终止该 Job 的 Worker 进程并回收许可证。

## 5. Result 与 Artifact

成功 Result 必须实现 `ObjectiveResultManifest`，带 `run_id`、`input_sha256`、`process`、`scope_id`、`scope_version` 和 `producer_version`；其中必须且只能包含一个 `kind=measurements` Artifact，并包含每个 Operation 声明的 `required_artifacts`。局部证据链使用 `scalar_field`、`render_scene` 和 `topology_map`。每个 Artifact 提供稳定且唯一的 `artifact_id`、单层安全 `filename`、`media_type`、`sha256` 和 `size_bytes`。Hermes 先校验 Result 身份，再下载并重新校验大小和哈希。

Measurement artifact 必须满足 `measurement.schema.json`，且 `producer_contract=measurement_only`。场、场景和映射必须满足各自 Schema，并与同一 Run/输入哈希交叉校验。NX 不得返回生产 Evaluation、失败 Patch、截图或 Finding。

## 6. 错误

NX Server 可以在错误 details 中保留远端诊断码；Hermes 对外统一为：`objective_task_invalid`、`objective_input_invalid`、`objective_backend_unavailable`、`objective_calculation_failed`、`objective_result_invalid`、`objective_artifact_invalid`、`objective_protocol_invalid` 和 `run_cancelled`。

错误必须保留所选 Backend 和输入格式的上下文。NX production 的任何错误都不得触发 PythonOCC 自动降级。

## 7. 验收

- 共用 `tests/fixtures/dfm/nx/task_contract_*.json`；
- capability、请求、measurement、scalar field、render scene 和 topology map 通过正式 Schema；
- 上传、幂等、轮询、取消、崩溃恢复、Artifact 安全和哈希校验有真实 Server E2E；
- 同一 CAD 源导出的 STEP/Parasolid golden model 都真实进入 NX，required Quantities/Artifacts 全部返回，并能由同一套 Hermes 后处理生成 Evaluation、局部截图和 Finding；
- 两种格式按批准的数值容差和问题区域语义核对，不要求二进制结果或采样点逐点完全相同；
- PythonOCC STEP demo 回归独立于 NX 服务状态；NX production STEP 在 NX 不可用时必须明确失败，不能降级到 PythonOCC。
