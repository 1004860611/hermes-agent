# DFM 壁厚/拔模角当前版本冻结说明

> 状态：Hermes 侧冻结候选（2026-08-06）  
> 范围：注塑成型；壁厚与拔模角；PythonOCC demo 与 NX production  
> 生产发布状态：未通过。当前冻结的是公共数据契约与 Hermes 后处理基线；NX STEP/Parasolid 双格式实现、真实 NX Server、C++ Calculator、配对 Golden Model 和工程师签字仍未交付。

## 1. 冻结边界

两条链路只允许在输入适配和几何计算实现上不同：

```text
Demo:       STEP ------------> PythonOCC --\
                                             -> ObjectiveResultManifest
Production: STEP / .x_t ----> NX ---------/   -> Measurement + ScalarField
                                                 + RenderScene + TopologyMap
                                                 -> Hermes Rule Evaluation
                                                 -> Hermes Evidence Renderer
                                                 -> Finding -> JSON/Markdown/PPTX
```

Backend 不接收 Rule、阈值、截图数量、截图视角或 Finding 策略，也不返回 pass/fail、失败 Patch、截图、severity 或 recommendation。

当前代码已经具备 PythonOCC STEP demo 和公共后处理基线，但还没有完成 NX STEP production 实现。NX STEP loader 与 Parasolid loader 是 M2.6-A 的交付项；二者必须生成相同契约语义，生产选择 NX 后不得在失败时自动降级到 PythonOCC。

## 2. 已收口事项

1. `material` 与 `model_units` 已进入真实消费者：
   - `material=ABS` 在 Hermes 选择冻结的壁厚规则 profile；Material 不下沉到纯几何 Calculator。
   - `model_units=mm` 进入 `load_geometry.model_unit`；当前冻结版不猜单位，也不支持隐式英寸换算。
2. PythonOCC 与 NX 使用相同 `ObjectiveTaskRequest`。本地文件路径仅在 `LocalObjectiveWorkerRequest`，NX 的 `input_id` 仅在 HTTP Job envelope。
3. 两条链路统一使用 `ObjectiveResultManifest` Schema 2。Result 和每个 Artifact 都携带 Run/Input/Scope 身份、大小与 SHA256。
4. NX Analyzer 只保留公共 `validate_objective_result()`，旧的 Measurement/Geometry 重复校验已删除。
5. Capability contract version 固定为 2；运行阶段固定为 objective load/compute/materialize/ready、rule evaluation、evidence render、report materialize、complete。
6. 客观计算检查点使用 Operation 指纹。指纹包含输入 SHA256、Backend/算法版本、Operation 参数和依赖指纹；规则阈值不参与，所以只改规则会复用几何结果。恢复时重新校验大小/SHA256并改写新 Run 身份。
7. PythonOCC 真实 STEP E2E 与 141 项 DFM 回归已通过；NX JSON fixture 已覆盖 Task、Capability、Result Manifest、Measurement、ScalarField、RenderScene 和 TopologyMap Schema。

## 3. 数据隔离

- 项目目录是一级隔离边界；缓存和 Run Artifact 都位于各自项目目录。
- Artifact 身份使用 `(run_id, logical_id)`，项目 Manifest 以 `relative_path` 去重。
- Result 必须同时匹配 `run_id + input_sha256 + process + scope_id + scope_version`。
- 本地与 NX 下载结果都校验 `size_bytes + sha256`。
- 缓存 key 包含输入哈希和 Backend 版本；恢复后的 JSON 会写入当前 `run_id`。

因此，多人、多项目或同一项目多 Run 不会因为固定的 `field_draft` 等逻辑 ID 而互相覆盖。隔离保证依赖项目存储目录和访问控制；生产部署仍必须为租户目录配置相应权限。

## 4. Golden Model 发布门

仓库当前只有可执行 STEP 样件和 NX 中性结果 fixture，没有与其同版本、同坐标系的真实 Parasolid `.x_t`，也没有可调用的真实 NX Server。当前不能声明“NX STEP/Parasolid 双格式生产闭环通过”，也不能要求不同几何内核或文件格式产生逐采样点完全相同的数值。

冻结转生产前必须提供一对由同一 CAD 源导出的 STEP/Parasolid 文件，并冻结：

- 两个输入文件 SHA256、CAD 源版本、单位、材料和开模方向；
- PythonOCC Backend 版本、NX Calculator 版本，以及 NX STEP/Parasolid loader 版本；
- 壁厚、拔模角的数值容差和问题区域重叠率；
- NX `certification_report_sha256`；
- Hermes 生成的三视角证据与工程师审核记录。

验收必须真实执行三个入口：PythonOCC STEP demo、NX STEP production、NX Parasolid production。PythonOCC 与 NX、以及 NX 两种输入格式之间，按批准的数值容差和问题区域语义核对，不要求数值或采样点逐点完全相同。FakeNXClient 和静态 JSON fixture 只能作为协议测试，不能替代 NX 业务验收。

## 5. 冻结后的变更规则

以下变更必须提升 Objective Schema 或 Scope/Backend 版本，并重新运行配对 Golden Model：字段语义变化、单位归一化变化、Calculator 参数变化、ScalarField 采样语义变化、Artifact 身份变化或证据几何引用变化。仅修改 Hermes Rule 阈值时，不应让客观几何缓存失效，但必须重新生成 Evaluation、Evidence、Finding 和报告。
