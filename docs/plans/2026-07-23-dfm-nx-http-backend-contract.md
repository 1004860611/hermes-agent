# DFM NX HTTP Backend 服务与 C++ 插件契约

> 面向实施团队的完整模块、接口、数据 Schema、错误、安全、测试和验收要求见
> [NX Server 与 NX C++ 插件开发交接规格](2026-07-23-nx-server-plugin-development-spec.md)。
> M2.6 方向/区域任务的稳定 ID、任务参数、Capability 和 Measurement 回链见
> [DFM/NX Task Contract v2](../dfm-nx-task-contract-v2.md)。

## 1. 边界

Hermes 只通过 `HttpNXBackendClient` 访问 NX，不提供本地脚本或本地 NX fallback。
NX Server 是独立 Windows 服务，负责认证、输入上传、任务队列、许可证、NX Worker
进程池、取消和结果保存；现有 C++ 插件只在 NX Session 内执行白名单 calculator。

```text
Hermes DFM JobManager
  → HttpNXBackendClient
  → NX Server
  → NX Worker Pool
  → NX Session + C++ Plugin
  → measurements/artifacts
```

NX Server 不能修改 Hermes Manifest。Hermes Run 是用户侧权威状态，远端 `job_id` 只是
执行引用。服务不可用只影响 NX/Parasolid 组合，不影响 OpenCascade STEP。

## 2. HTTP API v1 与请求 Schema v1/v2

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

输入采用先登记、再流式上传、最后按 `input_id + sha256` 引用的流程。服务必须限制
文件大小、校验 SHA-256，并禁止客户端提交服务器本地任意路径。

能力响应示例：

```json
{
  "status": "available",
  "backend_version": "NX2406",
  "plugin_version": "1.0.0",
  "formats": {"parasolid_xt": "available", "step": "available"},
  "calculators": {
    "inspect_topology": "certified",
    "measure_draft": "experimental",
    "measure_wall_thickness": "not_implemented"
  },
  "details": {"license_slots": 2, "busy_slots": 0}
}
```

只有 `certified` calculator 可以产生生产 Finding。`experimental` 只允许诊断
Measurement，`not_implemented`/`license_missing` 必须在 Plan 前阻塞。上述字符串状态保留
给 v1 任务；带 `metric_refs`/`arguments` 的 v2 任务必须使用结构化 Calculator Definition，
并通过参数和认证范围校验。

## 3. NX Server 伪代码

```python
class NXServer:
    def create_input(metadata):
        validate_size_and_name(metadata)
        return input_store.reserve(metadata.sha256)

    def upload_input(input_id, stream):
        digest = stream_to_quarantine(stream)
        require(digest == reserved_sha256(input_id))
        atomically_publish_input(input_id)

    def create_job(request):
        validate_schema(request, versions={1, 2})
        validate_calculator_allowlist(request.operations)
        require_certified_capabilities(request)
        return queue.enqueue(request)

    def worker_loop():
        job = queue.claim_available_license_slot()
        workspace = create_isolated_workspace(job.id)
        nx = session_pool.acquire()
        try:
            result = nx_cpp_bridge.execute(job.request, workspace)
            validate_measurements_and_artifacts(result)
            result_store.publish(job.id, result)
            queue.succeed(job.id)
        except NXCrash:
            session_pool.discard(nx)
            queue.fail(job.id, code="nx_process_crashed")
        finally:
            release_license_and_workspace(job, nx)
```

每个 NX Session 同时只处理一个 Job；完成一定任务数或出现不健康状态后必须回收。
取消应先通知插件协作停止，超时后由 Server 终止对应 NX Worker 进程树。

## 4. C++ 插件伪代码

```cpp
class IDfmCalculator {
public:
    virtual CalculatorResult Execute(
        const PartContext& part,
        const CalculatorRequest& request,
        CancellationToken& cancellation) = 0;
};

CalculatorRegistry registry = {
    {"inspect_topology", std::make_unique<TopologyCalculator>()},
    {"measure_draft", std::make_unique<DraftCalculator>()},
    {"measure_wall_thickness", std::make_unique<WallThicknessCalculator>()}
};

BridgeResult ExecuteRequest(const BridgeRequest& request) {
    ValidateSchema(request);
    NXPart part = OpenPart(request.inputPath);
    for (const auto& operation : request.operations) {
        auto& calculator = registry.RequireAllowlisted(operation.calculatorId());
        result.measurements += calculator.Execute(part, operation, cancellation);
    }
    ClosePartAndClearSession(part);
    return result;
}
```

插件只输出客观 Measurement、几何引用、质量诊断和证据，不选择注塑/压铸阈值，
不生成最终严重程度，也不接受任意 DLL、脚本或函数路径。

## 5. 配置与凭据

```yaml
dfm:
  nx:
    endpoint: https://nx-dfm.internal
    request_timeout_seconds: 30
    poll_interval_seconds: 2
```

Bearer Token 属于机密，NX Client 从 `.env`/进程凭据中的 `NX_BACKEND_TOKEN` 读取；
endpoint、超时和轮询间隔只写 `config.yaml`，不新增非机密 `HERMES_*` 环境变量。

## 6. 实现顺序

1. NX Server 实现 capability、输入上传和 topology Job。
2. C++ 插件将现有算法抽到 calculator allowlist，并输出版本化 measurements.json。
3. 使用 Fake Client 契约测试对接，再进行真实服务 E2E。
4. 用同源 STEP/x_t 语料认证 calculator；通过前保持 experimental/blocked。
5. 验证许可证耗尽、NX 崩溃、超时、取消、重复提交和 Artifact 哈希错误。
