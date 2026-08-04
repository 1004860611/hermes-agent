# NX Server 与 NX C++ 插件开发交接规格

> 状态：待 NX 团队实施  
> Hermes 对接版本：NX HTTP API `v1`、请求 Schema `1`/`2`
> 目标读者：NX Server 开发团队、NX Open C++ 插件团队、测试/部署团队  
> Hermes 参考实现：`tools/dfm/backends/nx/`、`tools/dfm/analyzers/parasolid.py`

## 1. 目标和范围

本文是 NX 计算侧的独立开发规格。完成后，Hermes 用户上传 Parasolid `.x_t` 文件，
可以通过远程 NX Server 调用 NX C++ 插件执行确定性几何计算，并将标准
Measurement 和证据返回 Hermes；Hermes 再根据注塑或压铸规则生成 Evaluation 和
Finding。

M2.6 方向/区域任务遵循 [DFM/NX Task Contract v2](../dfm-nx-task-contract-v2.md)。本文中的
请求 v1 示例继续服务已有 topology 链路；NX Server 在迁移期必须同时接受请求 Schema
v1 和 v2。

目标调用链：

```text
Hermes DFM
  → HttpNXBackendClient
  → NX Server HTTP API
  → Input Store / Job Queue / License Scheduler
  → NX Worker Pool
  → NX Session + C++ DFM Plugin
  → Measurement / Artifact
  → NX Server Result Store
  → Hermes 下载并校验
```

本项目明确不包含：

- NX Server 选择注塑或压铸阈值；
- NX 插件生成最终风险等级或工艺建议；
- Hermes 本机启动 NX 或执行 Journal 的 fallback；
- 通过 GUI 自动化点击 NX 菜单；
- 接受任意脚本、DLL、C++ 类名或函数路径；
- NX Server 直接读写 Hermes Manifest 或项目数据库。

## 2. 系统职责

### 2.1 Hermes 已完成的职责

- `.x_t` 文件大小限制、SHA-256、项目隔离和版本登记；
- 本地轻量 `inspect_parasolid_xt()` 预检；
- 工艺选择、事实澄清、Plan 和 Run 生命周期；
- HTTP 输入上传、Job 提交、轮询、取消和 Artifact 下载；
- 远端 calculator 认证门控；
- Artifact 大小和 SHA-256 二次校验；
- Measurement → Evaluation → Finding；
- 本地持久化 `external_job_id`。

### 2.2 NX Server 必须承担的职责

- Bearer Token 认证和访问审计；
- 输入登记、流式上传、大小限制、SHA-256 校验和隔离保存；
- API Schema 校验、幂等提交和 Job 状态机；
- NX 版本、插件版本、格式和 calculator capability；
- 任务队列、优先级、并发和许可证槽管理；
- NX Worker 启动、健康检查、复用、回收和崩溃恢复；
- 取消、超时、进程树终止和许可证释放；
- C++ 插件请求/结果校验；
- Artifact 元数据、哈希、下载和保留策略；
- 结构化错误码，不把内部路径或调用栈返回给客户端。

### 2.3 NX C++ 插件必须承担的职责

- 在 NX Session 内打开 Server 提供的受控输入文件；
- 校验单位、Body 类型和几何前置条件；
- 只执行注册表中的白名单 calculator；
- 支持协作取消和阶段进度；
- 输出客观 Measurement、几何引用、质量信息和证据；
- 关闭 Part，释放 NX 对象并清理 Session 状态；
- 不包含工艺规则阈值和最终风险判断。

## 3. 推荐模块划分

### 3.1 NX Server

```text
nx-server/
├── api/
│   ├── authentication
│   ├── capabilities_controller
│   ├── inputs_controller
│   ├── jobs_controller
│   └── artifacts_controller
├── contracts/
│   ├── api_v1
│   ├── plugin_request_v1
│   └── plugin_result_v1
├── inputs/
│   ├── reservation_service
│   ├── streaming_upload
│   ├── hash_verifier
│   └── quarantine_store
├── jobs/
│   ├── job_repository
│   ├── state_machine
│   ├── idempotency
│   ├── scheduler
│   └── cancellation
├── nx_runtime/
│   ├── license_manager
│   ├── session_pool
│   ├── worker_process
│   ├── plugin_bridge
│   └── health_monitor
├── results/
│   ├── result_validator
│   ├── artifact_store
│   └── retention
├── security/
│   ├── path_policy
│   ├── limits
│   └── audit_log
└── diagnostics/
    ├── structured_logging
    └── metrics
```

### 3.2 NX C++ 插件

```text
nx-dfm-plugin/
├── bridge/
│   ├── RequestParser
│   ├── RequestValidator
│   ├── Dispatcher
│   ├── ResultWriter
│   └── CancellationToken
├── model/
│   ├── PartLoader
│   ├── UnitNormalizer
│   ├── GeometryIndex
│   └── GeometryReferenceMapper
├── calculators/
│   ├── IDfmCalculator
│   ├── CalculatorRegistry
│   ├── TopologyCalculator
│   ├── DraftCalculator
│   ├── WallThicknessCalculator
│   └── UndercutCalculator
├── evidence/
│   ├── HighlightExporter
│   └── ImageRenderer
└── diagnostics/
    ├── NxErrorMapper
    └── TimingRecorder
```

不存在 calculator 消费者前，不提前创建空实现；首个交付只需要 topology 垂直链路。

## 4. HTTP 通用要求

### 4.1 Base URL 和版本

```text
https://<nx-server>/v1/...
```

所有 JSON 使用 UTF-8，字段名使用 `snake_case`。服务端可增加客户端忽略的字段，但
不得删除或改变 v1 已定义字段的语义。破坏性变更必须发布 `/v2`。

### 4.2 认证

请求头：

```http
Authorization: Bearer <NX_BACKEND_TOKEN>
Accept: application/json
```

上传内容使用：

```http
Content-Type: application/octet-stream
Content-Length: <bytes>
```

Token 必须从机密管理系统注入。日志不能记录完整 Token、模型内容或用户技术参数。

### 4.3 响应约束

- JSON endpoint 必须返回 JSON object，不能返回顶层数组或 HTML 错误页；
- `progress_percent` 必须为 `0..100` 整数；
- ID 仅允许安全字符，建议 `nxinput_<hex>`、`nxjob_<hex>`、`nxartifact_<hex>`；
- 时间使用 UTC ISO-8601；
- 客户端超时不代表 Server 应取消 Job；取消必须显式调用 cancel API。

## 5. API 详细契约

### 5.1 查询能力

```http
GET /v1/capabilities
```

成功响应：

```json
{
  "status": "available",
  "backend_version": "NX2406",
  "plugin_version": "1.0.0",
  "formats": {
    "parasolid_xt": "available",
    "step": "available"
  },
  "calculators": {
    "inspect_topology": "certified",
    "inspect_small_features": "not_implemented",
    "measure_planar_spacing": "not_implemented",
    "inspect_face_quality": "not_implemented",
    "inspect_cylindrical_features": "not_implemented",
    "measure_wall_thickness": "experimental",
    "measure_draft": {
      "status": "experimental",
      "contract_version": 2,
      "implementation_version": "nx-draft-v1",
      "required_arguments": ["pull_direction", "region"],
      "optional_arguments": ["excluded_regions"],
      "output_quantities": ["draft_angle_deg", "below_threshold_area_mm2"],
      "certification_scope": {
        "supports_directional_analysis": true,
        "supports_region_filter": true
      }
    },
    "inspect_surface_continuity": "not_implemented",
    "inspect_undercut": "license_missing"
  },
  "details": {
    "nx_version": "2406.4000",
    "api_schema_versions": [1, 2],
    "plugin_schema_versions": [1, 2],
    "license_slots": 2,
    "busy_slots": 0,
    "queue_depth": 0
  }
}
```

允许的 Backend 状态：

| 状态 | 含义 |
| --- | --- |
| `available` | 可以接受 Job |
| `degraded` | 部分 Worker/许可证异常，仍可接受有限 Job |
| `unhealthy` | 不可接受 Job |
| `maintenance` | 维护中 |

格式状态：`available`、`not_implemented`、`license_missing`、
`unsupported_version`、`disabled`。

Calculator 状态：

| 状态 | 是否允许生产 Plan |
| --- | --- |
| `certified` | 是 |
| `experimental` | 否，只能内部验证 |
| `not_implemented` | 否 |
| `license_missing` | 否 |
| `disabled` | 否 |

Hermes 当前严格要求 Plan 中除加载/渲染外的 operation 均为 `certified`。

### 5.2 登记输入

```http
POST /v1/inputs
Content-Type: application/json
```

请求：

```json
{
  "sha256": "64位小写十六进制",
  "size_bytes": 12582912,
  "filename": "housing.x_t"
}
```

新输入响应：

```json
{
  "input_id": "nxinput_01abc",
  "upload_required": true
}
```

相同内容已存在时允许去重：

```json
{
  "input_id": "nxinput_existing",
  "upload_required": false
}
```

要求：

- `filename` 只作显示，不得用作服务器存储路径；
- 校验文件大小上限；
- 只允许已配置后缀和 MIME 策略；
- 去重至少按租户/安全域隔离，不能泄露其他租户文件是否存在；
- 未完成上传的 reservation 必须过期清理。

### 5.3 上传输入内容

```http
PUT /v1/inputs/{input_id}/content
Content-Type: application/octet-stream
Content-Length: 12582912
```

Hermes 以分块方式发送原始文件。Server 必须边接收边计算 SHA-256，先写隔离临时文件，
只有大小和哈希都匹配 reservation 才能原子发布。

成功可以返回空 body 或 JSON object；HTTP 状态必须为 2xx。

### 5.4 提交 Job

```http
POST /v1/jobs
Content-Type: application/json
```

Hermes 当前发送的完整请求：

```json
{
  "schema_version": 1,
  "run_id": "run_0123456789abcdef",
  "process": "die_casting",
  "scope_id": "die_casting.topology-baseline",
  "scope_version": "1.0.0",
  "operations": [
    {
      "operation_id": "step.load",
      "operation": "load_step",
      "depends_on": []
    },
    {
      "operation_id": "step.topology",
      "operation": "inspect_topology",
      "depends_on": ["step.load"]
    }
  ],
  "parameters": {},
  "input": {
    "input_id": "nxinput_01abc",
    "sha256": "64位小写十六进制",
    "format_id": "parasolid_xt"
  }
}
```

兼容要求：v1 的 `load_step` 是历史 operation 名。对于 `format_id=parasolid_xt`，
Server/插件必须把它解释为“加载当前几何输入”，不能要求输入一定是 STEP。若改为
`load_geometry`，必须发布新的请求 Schema 或在服务端同时兼容旧名。

M2.6 六方向/区域任务使用请求 Schema v2。v2 将 v1 的 `operation` 明确命名为
`calculator_id`，并增加业务 Metric 引用和任务级参数：

```json
{
  "schema_version": 2,
  "operations": [
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
  ]
}
```

字符串状态是 v1 Calculator 的兼容形式；包含 `metric_refs` 或 `arguments` 的 v2 任务必须
匹配结构化 Definition。Hermes 会校验状态、`contract_version`、必需参数和允许参数，不能
用一个笼统的 `certified` 声明覆盖尚未认证的方向或区域能力。

`operation_id` 标识本次 Plan 的任务实例，`calculator_id` 标识通用算法。六个方向分别
使用唯一 `operation_id` 和参数，但共同使用 `measure_draft`。Server 必须拒绝缺少必需
参数或超出 capability 认证范围的 v2 任务。

`parameters` 的值结构为：

```json
{
  "pull_dir": {
    "value": [0.0, 0.0, 1.0],
    "unit": null,
    "source": "project_fact",
    "kind": "engineering_context"
  },
  "min_draft_deg": {
    "value": 1.0,
    "unit": "degree",
    "source": "injection_legacy_default",
    "kind": "rule"
  }
}
```

插件只应使用 calculator 的工程上下文或算法参数。规则阈值可以随请求传递用于兼容，
但 NX 插件不得输出最终 pass/fail；正式 Evaluation 由 Hermes 生成。

成功响应：

```json
{
  "job_id": "nxjob_01abc",
  "status": "queued",
  "stage": "queued",
  "progress_percent": 0,
  "error": null
}
```

幂等要求：相同授权域中的相同 `run_id + input.sha256 + schema_version` 重复提交必须
返回同一个 Job，或返回可识别的冲突；不能重复占用许可证并执行两次。

### 5.5 查询 Job

```http
GET /v1/jobs/{job_id}
```

响应：

```json
{
  "job_id": "nxjob_01abc",
  "status": "running",
  "stage": "inspect_topology",
  "progress_percent": 45,
  "error": null
}
```

Job 状态固定为：

```text
queued → starting → running → succeeded
                            ↘ failed
queued/running/starting    → cancelling → cancelled
```

Hermes 当前终态识别为 `succeeded`、`failed`、`cancelled`。`starting`、`running`、
`cancelling` 都会继续轮询。

推荐阶段：

```text
queued
waiting_for_license
starting_nx
loading_part
validating_geometry
inspect_topology
measure_draft
measure_wall_thickness
rendering_evidence
publishing_result
complete
```

进度不能倒退。

### 5.6 取消 Job

```http
POST /v1/jobs/{job_id}/cancel
Content-Type: application/json

{}
```

响应必须使用与 Job 查询相同的结构。取消必须幂等：重复取消已取消 Job 返回
`cancelled`；取消已完成 Job返回其终态，不创建新 Job。

执行策略：

1. 设置 Server cancellation flag；
2. 通知 C++ 插件在 calculator 安全点退出；
3. 等待可配置 grace period；
4. 超时后终止该 Job 对应 NX Worker 进程树；
5. 回收许可证和临时目录；
6. 原子写入 `cancelled`。

### 5.7 查询结果

```http
GET /v1/jobs/{job_id}/result
```

仅成功 Job 返回结果：

```json
{
  "job_id": "nxjob_01abc",
  "status": "succeeded",
  "artifacts": [
    {
      "artifact_id": "nxartifact_measurements",
      "kind": "measurements",
      "filename": "measurements.json",
      "media_type": "application/json",
      "sha256": "64位小写十六进制",
      "size_bytes": 20480
    },
    {
      "artifact_id": "nxartifact_evidence_001",
      "kind": "evidence_image",
      "filename": "draft_region_001.png",
      "media_type": "image/png",
      "sha256": "64位小写十六进制",
      "size_bytes": 175320
    }
  ]
}
```

强制要求：

- 至少包含且只包含一个 `kind=measurements`；
- `filename` 必须是单层安全文件名，不能包含 `/`、`\\`、`..` 或绝对路径；
- `artifact_id` 在 Job 内唯一；
- `size_bytes` 与下载字节一致；
- `sha256` 与下载内容一致；
- Artifact 发布后不可修改。

### 5.8 下载 Artifact

```http
GET /v1/jobs/{job_id}/artifacts/{artifact_id}
```

响应为原始字节，支持流式传输。必须校验调用者有权访问对应 Job。Hermes 下载后会
再次计算大小和 SHA-256，不一致时整个 DFM Run 失败为 `nx_artifact_invalid`。

## 6. Measurement Artifact 契约

`measurements.json` 是 NX 侧最重要的输出，顶层必须为 JSON object：

```json
{
  "schema_version": 1,
  "run_id": "run_0123456789abcdef",
  "input_sha256": "64位小写十六进制",
  "process": "die_casting",
  "scope_id": "die_casting.topology-baseline",
  "backend": {
    "id": "siemens_nx",
    "nx_version": "2406.4000",
    "plugin_version": "1.0.0"
  },
  "operations": ["load_step", "inspect_topology"],
  "producer_contract": "measurement_only",
  "measurements": []
}
```

单条 Measurement：

```json
{
  "measurement_id": "measurement-model-valid-brep",
  "check_id": "model_geometry",
  "metric": "valid_brep",
  "value": true,
  "unit": null,
  "status": "measured",
  "geometry_refs": [],
  "method": "nx_open_check_body",
  "algorithm_version": "nx-topology-v1",
  "input_sha256": "64位小写十六进制",
  "quality": {
    "exact": true
  },
  "diagnostics": {}
}
```

请求 Schema v2 对应的 Measurement 增加以下稳定回链字段：

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

`operation_ref` 必须引用提交 Plan 中的任务；`calculator_id` 必须与该任务一致；`metric_id`
必须属于该任务的 `metric_refs`；v2 中 `check_id` 与 `operation_ref` 相同。`metric` 表示具体
测量量，不代替业务 Metric ID。

几何引用：

```json
{
  "kind": "face",
  "index": 17,
  "input_sha256": "64位小写十六进制"
}
```

当前 Hermes Measurement v1 识别 `kind=face|edge|solid|vertex` 和整数 `index`。
NX 插件可以在 `diagnostics` 中额外保存 NX persistent identifier，但不能只返回无法被
Hermes 使用的 NX 内存句柄。`index` 必须在同一不可变输入和同一插件版本下可重复。

NX 插件和 NX Server 只输出 Measurement，不输出 Evaluation。Hermes 在 Artifact
下载和哈希校验后，由统一 `EvaluationEngine` 使用持久化 Plan 参数和版本化规则生成
独立 `evaluations.json`；随后 Finding 层消费该 Artifact。Server 返回的 Evaluation
字段不会作为生产结论使用。

## 7. C++ 插件内部请求契约

HTTP Server 与插件之间不通过网络开放。推荐由 Server 写入隔离 Job 目录：

```text
jobs/<job_id>/
├── input/part.x_t
├── request/plugin_request.json
├── output/
├── logs/
└── cancel.flag
```

`plugin_request.json`：

```json
{
  "schema_version": 1,
  "job_id": "nxjob_01abc",
  "input_path": "D:/nx-jobs/nxjob_01abc/input/part.x_t",
  "input_sha256": "...",
  "format_id": "parasolid_xt",
  "output_dir": "D:/nx-jobs/nxjob_01abc/output",
  "cancel_path": "D:/nx-jobs/nxjob_01abc/cancel.flag",
  "operations": [
    {
      "operation_id": "step.topology",
      "operation": "inspect_topology",
      "depends_on": ["step.load"]
    }
  ],
  "parameters": {}
}
```

路径全部由 Server 生成，不能直接使用 HTTP 请求提供的本地路径。启动插件桥时使用
argv，不拼接 shell 命令。插件只允许读当前 Job 输入、请求和取消文件，只允许写当前
Job 输出和日志目录。

## 8. C++ Calculator 接口

推荐接口：

```cpp
struct CalculatorContext {
    NXOpen::Part* part;
    GeometryIndex* geometryIndex;
    CancellationToken* cancellation;
    ProgressSink* progress;
    std::filesystem::path outputDirectory;
};

class IDfmCalculator {
public:
    virtual ~IDfmCalculator() = default;
    virtual std::string Id() const = 0;
    virtual std::string Version() const = 0;
    virtual CapabilityStatus Capability(const NXLicenseState&) const = 0;
    virtual CalculatorResult Execute(
        const CalculatorContext& context,
        const CalculatorRequest& request) = 0;
};
```

注册表只接受编译期或受信配置中的稳定 ID：

```cpp
registry.Register("inspect_topology", MakeTopologyCalculator());
registry.Register("measure_draft", MakeDraftCalculator());
registry.Register("measure_wall_thickness", MakeWallThicknessCalculator());
```

禁止：

- 从请求加载 DLL；
- 将 operation 解释成 C++ symbol；
- 执行请求携带的 Python/Journal；
- 调用任意 shell；
- 用 LLM 或视觉模型生成测量数值。

## 9. 首批 Calculator 开发内容

### 9.1 第一批：必须完成

#### `inspect_topology`

输入：已加载 Part/Body。输出至少包括：

- `valid_brep`；
- solid、sheet body 数量；
- face、edge、vertex 数量；
- 包围盒和单位；
- 无效 Body/Face 的几何引用；
- NX API 方法和插件算法版本。

认证后 capability：

```json
{"inspect_topology": "certified"}
```

这是压铸 `.x_t` 第一条 E2E 的最低交付范围。

### 9.2 第二批：建议顺序

1. `measure_draft`；
2. `measure_wall_thickness`；
3. `inspect_undercut`；
4. `inspect_cylindrical_features`；
5. `inspect_face_quality`；
6. `inspect_surface_continuity`；
7. 证据渲染。

每个 calculator 必须单独认证；不能因为插件整体可用就全部返回 `certified`。

## 10. 几何计算和认证要求

每个 calculator 建立 Definition：

```json
{
  "calculator_id": "measure_draft",
  "implementation_version": "nx-draft-v1",
  "required_inputs": ["brep", "pull_dir"],
  "output_metrics": ["draft_angle_deg"],
  "numerical_contract": {
    "unit": "degree",
    "absolute_tolerance": 0.1
  }
}
```

认证使用同源 CAD 导出的成对 STEP/`x_t` 语料，比较工程不变量而不是 Face 编号：

| Calculator | 必须比较 |
| --- | --- |
| topology | Body 类型、数量、有效性、bbox、面积、体积 |
| draft | 最小角度、负拔模面积、区域空间位置 |
| thickness | 最小值、分位数、薄壁区域重合度、无效采样率 |
| undercut | 是否存在、区域面积、空间位置、方向关系 |

认证状态只能由版本化测试报告产生：

```text
not_implemented → experimental → certified
```

代码发布或 NX 版本变化后，如果数值行为可能变化，应重新认证并更新
`plugin_version`/calculator version。

## 11. NX Session 和许可证管理

### 11.1 Worker Pool

- 一个 NX Session 同时只处理一个 Job；
- Worker 数量不得超过可用许可证槽；
- Job 完成后必须关闭 Part、清除显示/选择状态和插件缓存；
- Worker 处理可配置数量 Job 后主动回收；
- NX 崩溃后丢弃 Worker，不能复用其 Session；
- `waiting_for_license` 必须作为可见 stage，而不是立即失败。

### 11.2 超时

至少定义：

- 队列等待超时；
- 许可证等待超时；
- NX 启动超时；
- Part 加载超时；
- 单 calculator 超时；
- 总 Job 超时；
- 取消 grace period。

超时必须输出具体错误码并终止/回收对应 Worker，不能让许可证永久占用。

## 12. 错误契约

Job 失败响应：

```json
{
  "job_id": "nxjob_01abc",
  "status": "failed",
  "stage": "loading_part",
  "progress_percent": 8,
  "error": {
    "code": "nx_input_unsupported_version",
    "message": "The Parasolid version is not supported by this NX runtime.",
    "details": {
      "format_id": "parasolid_xt"
    },
    "retryable": false
  }
}
```

建议错误码：

| 错误码 | retryable | 含义 |
| --- | ---: | --- |
| `authentication_failed` | 否 | Token 无效 |
| `input_too_large` | 否 | 超过大小限制 |
| `input_hash_mismatch` | 否 | 上传内容哈希不符 |
| `input_not_found` | 否 | input_id 不存在/无权访问 |
| `request_schema_unsupported` | 否 | Schema 版本不支持 |
| `operation_unsupported` | 否 | operation 不在白名单 |
| `calculator_not_certified` | 否 | 未达到生产认证 |
| `nx_license_unavailable` | 是 | 暂无许可证 |
| `nx_start_timeout` | 是 | NX 启动超时 |
| `nx_process_crashed` | 是 | NX Worker 崩溃 |
| `nx_input_open_failed` | 视原因 | NX 无法打开模型 |
| `nx_input_unsupported_version` | 否 | Parasolid 版本不支持 |
| `nx_geometry_invalid` | 否 | 几何不满足 calculator 前置条件 |
| `calculator_failed` | 视原因 | calculator 执行失败 |
| `job_timeout` | 是 | 总任务超时 |
| `job_cancelled` | 否 | 用户取消 |
| `artifact_generation_failed` | 是 | 结果/证据生成失败 |
| `internal_error` | 是 | 已净化的未知错误 |

HTTP 层推荐：400 请求错误、401/403 鉴权、404 不存在、409 状态/幂等冲突、413 文件
过大、422 Schema/operation、429 队列限流、5xx 服务异常。进入队列后的工程错误通过
Job `failed` 返回，不把 NX 内部异常直接映射为任意 HTTP 500。

## 13. 安全要求

- 所有输入、文件名、技术属性和插件输出均视为不可信；
- 上传前限制 Content-Length，接收中再次限制实际字节数；
- Job 工作目录必须位于配置根目录，所有路径 canonicalize 后校验 containment；
- 不使用用户文件名作为物理路径；
- NX Worker 使用低权限专用账号；
- NX Server 不对外暴露 NX 安装目录和 Job 本地路径；
- Artifact 下载必须校验租户和 Job 所有权；
- 日志脱敏，不记录模型原文、Token、完整技术说明；
- 设置输入、结果、日志和失败 Job 的保留/安全删除策略；
- 对 NX/C++ 依赖执行版本、许可证和供应链审查；
- 生产必须使用 TLS；
- 不提供任意代码执行、任意路径读取或通用 NX Open RPC。

## 14. 可观测性

Server 应记录：

- request/job/input/artifact ID；
- 授权主体，但不记录 Token；
- NX、插件和 calculator 版本；
- 每个 stage 开始/结束和耗时；
- 队列、许可证等待、NX 启动、加载和计算耗时；
- Worker PID/Session ID（仅内部日志）；
- 状态迁移和取消原因；
- 净化后的错误码。

建议指标：队列深度、许可证占用、活跃 Worker、Job 成功率、P50/P95 耗时、NX 崩溃
次数、取消耗时、Artifact 字节量。禁止默认出站遥测；监控只进入受控内部系统。

## 15. 测试要求

### 15.1 Server 单元/集成测试

- capability 字段和状态枚举；
- 输入 reservation、去重、过期、大小和哈希；
- 分块上传中断及重试；
- Job Schema、operation 白名单和依赖顺序；
- `run_id` 幂等提交；
- 状态合法迁移和进度不倒退；
- 并发/许可证限流；
- 取消 queued/running/terminal Job；
- Worker 崩溃和自动回收；
- Artifact 文件名、大小、哈希和权限；
- Token、路径穿越和跨租户访问。

### 15.2 插件测试

- `.x_t` 支持版本矩阵；
- 单位、坐标系、Body/Solid/Sheet Body；
- 损坏、空模型、多 Body、开放 Shell；
- calculator 的正常、边界和取消安全点；
- NX 对象和 Part 清理；
- 相同输入/版本结果可重复；
- 输出 Schema 和几何引用稳定性。

### 15.3 Hermes 联调 E2E

至少覆盖：

1. capability available；
2. `.x_t` 上传和 SHA-256 一致；
3. 压铸 topology Plan 成功；
4. `measurements.json` 下载并登记；
5. 远端进度映射到 Hermes Run；
6. 用户取消传播到 NX Job；
7. Server 不可达只影响 Parasolid；
8. calculator experimental 时 Plan blocked；
9. Artifact 哈希错误时 Run failed；
10. NX 崩溃时返回结构化错误且许可证被回收；
11. 重复提交不重复执行；
12. STEP/OpenCascade 注塑回归保持通过。

## 16. 分阶段交付

### 阶段 A：契约 Mock

- 实现全部 HTTP endpoint；
- 使用假 Worker 返回标准 Measurement；
- 通过 Hermes `HttpNXBackendClient` 集成测试；
- capability 中 calculator 保持 `experimental`。

### 阶段 B：真实 NX Topology 垂直链路

- NX Server 启动一个 NX Worker；
- C++ 插件读取 `.x_t`；
- 实现 `inspect_topology`；
- 输出标准 `measurements.json`；
- 完成取消、超时和崩溃回收；
- 通过真实 Hermes E2E 后标记 `certified`。

Topology 垂直链路只是技术冒烟，不是 NX DFM 第一阶段业务完成标准。

### 阶段 C：黄金产品所需 Calculator 和完整生产链

- 冻结黄金产品追溯矩阵；
- 冻结 Task Contract v2，并通过 Hermes/NX 共用 fixture 的双向契约测试；
- 实现该产品所需全部 calculator；
- 返回 Measurement-only Artifact 和 Evidence；
- 由 Hermes EvaluationEngine/FindingEngine 完成规则评价和报告；
- 形成只读 Run Bundle；
- 模具工程师在生产 Run 完成后使用 Ground Truth 人工核对结果，不开发自动比较程序，
  Ground Truth 不进入 NX Server、插件或 Hermes 生产运行时。

### 阶段 D：有限 Worker Pool

- 按许可证槽建立 Worker Pool；
- 队列、健康检查、定期回收；
- 并发和许可证耗尽测试；
- 部署、升级和回滚手册。

### 阶段 E：逐项增加计算器和代表性产品

- draft；
- wall thickness；
- undercut；
- 其他批准的 NX 能力；
- 每项独立语料、误差契约和认证报告。

## 17. 最低完成定义

NX 团队交付第一版前必须同时满足：

- API v1 全部 endpoint 与本文件一致；
- Token、输入流式上传、大小和 SHA-256 校验可用；
- Job 状态机、幂等、取消、超时和错误码可用；
- NX Worker 能打开批准版本的 `.x_t`；
- C++ 插件实现白名单 `inspect_topology`；
- capability 只把真实认证能力标记为 `certified`；
- 结果至少包含一个有效 `measurements.json`；
- Artifact 文件名、大小和哈希契约通过；
- Worker 崩溃后不遗留许可证和长期 NX 进程；
- Server/插件测试和真实 Hermes E2E 通过；
- 同一输入、NX 版本和插件版本重复运行产生工程等价结果；
- 部署、配置、许可证、升级、回滚和故障排查文档齐全。

## 18. 对接资料和负责人需要确认的事项

开发启动前，NX 团队需要给出：

1. 目标 NX 版本和补丁版本；
2. C++ 插件当前入口方式和已实现 calculator；
3. 可用许可证模块和并发槽数；
4. NX 是否支持目标服务器环境的无交互运行；
5. `.x_t` 目标版本范围；
6. Worker 启动、加载插件、退出和强制终止方式；
7. 第一批脱敏 STEP/`x_t` 同源样件；
8. 计算结果的误差批准人；
9. NX Server 部署网络、TLS、Token 和存储策略；
10. Artifact 保留和产品知识产权安全要求。

上述事项影响部署和认证，但不改变 HTTP v1 的基础职责边界。
