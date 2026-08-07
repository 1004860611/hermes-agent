# NX Server 与 NX C++ 插件开发交接规格

> 状态：待 NX 团队实施与联合评审
> HTTP API：`/v1`
> Objective Task/Result Schema：`2`；Measurement/ScalarField/RenderScene/TopologyMap Schema：`1`
> 数据契约：[DFM/NX Production Task Contract](../dfm-nx-task-contract.md)

## 1. 目标

NX 计算侧接收 STEP/STP 和 Parasolid `.x_t`，在受控 NX Session 中执行相同白名单
Calculator，返回 `ObjectiveResultManifest`、标准 Measurement 与中性几何 Artifact。Hermes
负责事实、规则、计划、Evaluation、Evidence 和 Finding；NX 不持有或修改 Hermes Manifest。

```text
Hermes -> NX HTTP Server -> Input Store / Job Queue / License Scheduler
       -> NX Worker -> C++ Calculator -> Measurement / Artifact -> Hermes
```

## 2. 模块

- API：认证、限流、请求 Schema 校验、Job/Artifact endpoint；
- Input Store：隔离上传、SHA-256 校验、原子发布和生命周期清理；
- Scheduler：Job 状态机、幂等、许可证槽、超时和取消；
- Worker：每 Job 隔离目录、NX Session 生命周期、崩溃恢复；
- C++ Bridge：解析 Operation，按 allowlist 调用 Calculator；
- Calculator Registry：声明结构化 capability 和实现版本；
- Result Store：原子发布 ObjectiveResultManifest 和带大小/SHA256的 Artifact。

## 3. 唯一请求模型

Server 只接受 Objective Task/Result `schema_version=2`。HTTP Job 使用传输外壳：

```text
NX Job Envelope
├── schema_version=2
├── input: input_id + sha256 + format_id(step|parasolid_xt)
└── task: ObjectiveTaskRequest
```

`ObjectiveTaskRequest` 使用正式 Operation 字段：`operation_id`、`calculator_id`、
`depends_on`、`metric_ids`、`required_quantities`、`required_artifacts`、`arguments`、
`algorithm_options`。

统一使用 `geometry.load` / `load_geometry`。不接受 `operation`、`metric_refs`、`fact_ref`、`region_ref`、`check_id` 或 `operation_ref`。Rule 阈值不得进入插件输入。

Task 包含 `run_id`、`input_sha256`、`input_format` 和 process/scope 身份；`input_id` 只属于
HTTP 传输外壳。Server 必须验证外壳和 Task 的 SHA256/格式一致。完整结构见
`objective_task.schema.json` 和 `nx_request.schema.json`。

## 4. Capability

每个 Calculator 必须返回结构化 Definition：认证状态、契约版本、实现版本、必需/可选参数、输出 Quantities、输出 Artifact kinds、支持格式、Region modes、NX versions 和认证报告哈希。字符串 `"certified"` 不是合法 capability。

Server 在排队前完成全部能力校验。C++ Registry 也需校验 allowlist，形成纵深防御。

M2.6-A 中 `formats` 至少分别声明 `step` 和 `parasolid_xt`。每个 Calculator 的
`supported_formats` 也必须逐格式认证，不能因为 NX 能打开 STEP 就推断壁厚/拔模角已经认证。

## 5. Measurement

每条 Measurement 必须包含 `measurement_id`、`operation_id`、`calculator_id`、`metric_id`、`quantity_id`、值/单位、几何/区域引用、场引用、方法、算法版本和输入哈希。

需要局部证据的 Calculator 额外返回 ScalarField、RenderScene 和 TopologyMap。NX 只返回客观值和中性几何，不得使用 `violating`/`failed` 命名。`pass/fail`、失败 Patch、截图、severity、rule、recommendation 属于 Hermes，不得由插件生成。完整结构见 `measurement.schema.json`、`scalar_field.schema.json`、`render_scene.schema.json` 和 `topology_map.schema.json`。

成功 Job 的 `/result` 必须返回 `ObjectiveResultManifest`，其中 `run_id`、`input_sha256`、
`process`、`scope_id`、`scope_version` 和 `producer_version` 完整，并为每个 Artifact 提供
`artifact_id`、`kind`、单层 `filename`、`media_type`、`size_bytes` 和 `sha256`。不得只返回
缺少 Run/Input 身份的裸 Artifact 数组。

## 6. 安全与运行

- 服务账号最小权限，Job 工作目录隔离；
- 不接受任意路径、命令、脚本或动态 Calculator 名；
- 上传大小、扩展名、格式和哈希均校验；
- STEP 与 Parasolid 进入格式隔离的 loader，但规范化后的单位、坐标系、GeometryRef、场和
  Measurement 语义必须一致；
- 日志不记录 token、文件正文或未脱敏客户路径；
- 取消先协作退出，超时后只终止对应 Worker；
- NX 崩溃后丢弃 Session，不复用未知状态进程；
- Artifact 文件名必须是单层安全名称，下载需授权与哈希校验。
- production 配置选择 NX 后，STEP 导入或 Calculator 失败必须返回公共 `objective_*`
  错误，不得静默转给 PythonOCC；PythonOCC 只属于独立 demo 部署模式。

## 7. 测试

1. 使用 Hermes 共用 fixtures 做双向解析测试；
2. 对缺字段、未知字段、错误 Schema、字符串 capability 做负例；
3. 对缺参数、额外参数、缺 Quantity/Artifact、错误 Region mode/格式做能力负例；
4. 对上传中断、哈希错误、重复提交、许可证耗尽、取消和 NX crash 做集成测试；
5. 用同源 STEP/Parasolid 配对样件在真实 NX 中分别打开，执行 topology、壁厚和拔模角；
6. 验证两种格式均返回 Schema 2 Result Manifest，并可被 Hermes 完整回链生成
   Evaluation/失败 Patch/三视角截图/Finding；
7. 对同一 Run、输入哈希、格式错配、跨 Run Artifact 和内容哈希做负例；
8. 固化 NX、插件、每格式 Calculator 和认证报告版本。

## 8. 交付门槛

- Hermes/NX 共用 Schema 与 fixture 全部通过；
- API、Worker、C++ Registry 不存在另一套 demo 解析路径；
- M2.6-A 的 STEP/Parasolid loader、壁厚和拔模角均有认证范围与报告哈希；
- 真实部署完成上传、执行、取消、下载和崩溃恢复 E2E；
- 当前正式 Scope 在两个格式上完成真实 E2E；后续每个黄金产品指标按独立增量重复同一门槛；
- 文档状态在联合评审前保持 Proposed，M2.6-A 真实 E2E 后冻结基础 Calculator 范围，
  M2.6-C 人工签字后才声明完整黄金产品闭环完成。
