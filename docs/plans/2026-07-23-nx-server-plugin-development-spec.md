# NX Server 与 NX C++ 插件开发交接规格

> 状态：待 NX 团队实施与联合评审
> HTTP API：`/v1`
> 唯一数据 Schema：`1`
> 数据契约：[DFM/NX Production Task Contract](../dfm-nx-task-contract.md)

## 1. 目标

NX 计算侧接收 Parasolid `.x_t`，在受控 NX Session 中执行白名单 Calculator，返回标准 Measurement 与 Artifact。Hermes 负责事实、规则、计划、Evaluation 和 Finding；NX 不持有或修改 Hermes Manifest。

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
- Result Store：原子发布 Measurement/Artifact manifest。

## 3. 唯一请求模型

Server 只接受 `schema_version=1` 和正式 Operation 字段：`operation_id`、`calculator_id`、`depends_on`、`metric_ids`、`required_quantities`、`arguments`、`algorithm_options`。

统一使用 `geometry.load` / `load_geometry`。不接受 `operation`、`metric_refs`、`fact_ref`、`region_ref`、`check_id` 或 `operation_ref`。Rule 阈值不得进入插件输入。

Job 请求还包含 `run_id`、process/scope 身份和 `input_id + sha256 + format_id`。完整结构见 `nx_request.schema.json`。

## 4. Capability

每个 Calculator 必须返回结构化 Definition：认证状态、契约版本、实现版本、必需/可选参数、输出 Quantities、支持格式、Region modes、NX versions 和认证报告哈希。字符串 `"certified"` 不是合法 capability。

Server 在排队前完成全部能力校验。C++ Registry 也需校验 allowlist，形成纵深防御。

## 5. Measurement

每条 Measurement 必须包含 `measurement_id`、`operation_id`、`calculator_id`、`metric_id`、`quantity_id`、值/单位、几何/区域引用、方法、算法版本和输入哈希。

NX 只返回客观结果。`pass/fail`、severity、rule、recommendation 属于 Hermes，不得由插件生成。完整结构见 `measurement.schema.json`。

## 6. 安全与运行

- 服务账号最小权限，Job 工作目录隔离；
- 不接受任意路径、命令、脚本或动态 Calculator 名；
- 上传大小、扩展名、格式和哈希均校验；
- 日志不记录 token、文件正文或未脱敏客户路径；
- 取消先协作退出，超时后只终止对应 Worker；
- NX 崩溃后丢弃 Session，不复用未知状态进程；
- Artifact 文件名必须是单层安全名称，下载需授权与哈希校验。

## 7. 测试

1. 使用 Hermes 共用 fixtures 做双向解析测试；
2. 对缺字段、未知字段、错误 Schema、字符串 capability 做负例；
3. 对缺参数、额外参数、缺 Quantity、错误 Region mode/格式做能力负例；
4. 对上传中断、哈希错误、重复提交、许可证耗尽、取消和 NX crash 做集成测试；
5. 用真实 NX 打开 golden part，执行 topology 和 P0 Calculator；
6. 验证结果可被 Hermes 完整回链并生成 Evaluation/Finding；
7. 固化 NX、插件、Calculator 和认证报告版本。

## 8. 交付门槛

- Hermes/NX 共用 Schema 与 fixture 全部通过；
- API、Worker、C++ Registry 不存在另一套 demo 解析路径；
- 每个 P0 Calculator 均有认证范围与报告哈希；
- 真实部署完成上传、执行、取消、下载和崩溃恢复 E2E；
- golden part 数值在工程师批准容差内；
- 文档状态在联合评审前保持 Proposed，完成真实 E2E 后再冻结。
