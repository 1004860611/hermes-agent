---
title: "DFM Hermes Agent 开发路径"
status: active
updated: 2026-08-12
type: product-development-plan
---

# DFM Hermes Agent 开发路径

本文只维护产品目标、阶段范围和验收门槛。系统架构、运行流程、NX 要求和数据契约见
[DFM 架构、工作流与 NX 契约](2026-08-12-dfm-architecture-workflow-and-nx-contract.md)。

## 1. 产品目标

用户提交三维模型和可选二维图纸后，Hermes 应完成：

```text
项目建档 → 信息提取 → 特征发现 → 事实确认 → 分析计划
→ 客观几何计算 → 确定性规则评价 → 证据截图 → Finding / Report
```

每个结论必须可追溯到输入、事实、特征区域、规则、计算结果和证据。LLM 负责理解、
澄清和解释，不生成几何值、工程阈值或 pass/fail。

## 2. 当前基线

当前正式 Scope：

| 项目 | 当前状态 |
| --- | --- |
| 工艺 | 注塑 `injection` |
| 指标 | 壁厚、拔模角 |
| 三维输入 | PythonOCC Demo 支持 STEP；NX Production 目标支持 STEP/Parasolid |
| 二维输入 | 契约和 Provider 占位，尚无生产识别 |
| 特征识别 | 普通全模型区域可运行；螺柱、筋、倒扣等 NX/MTK Recognizer 为显式占位 |
| 规则 | Hermes 侧版本化 Scope；当前 ABS 示例阈值仅用于已批准范围 |
| 证据 | Hermes 根据 ScalarField 和同源 RenderScene 生成三视角截图 |

已完成的基础能力包括项目 Manifest、两阶段发现骨架、区域化 AnalysisPlan、PythonOCC
壁厚/拔模角客观场、统一 Evaluation/Finding/Report，以及 Objective Schema 4 和几何证据
Schema 2。NX Server、NX Calculator 和真实工艺特征识别尚未交付，因此不能声明生产可用。

## 3. 开发阶段

### M2.6-A：当前 Scope 生产形态闭环

目标是用壁厚和拔模角验证完整架构，不扩大指标范围。

- 固定二维 Observation 接口，允许实现保持占位；
- 实现三维注塑特征识别的第一批真实能力，至少覆盖工程师批准的特征集合；
- Feature/Region 与 TopologySnapshot 绑定，普通剩余区域不漏算、不重复计算；
- NX 同时读取 STEP 和 Parasolid，输出统一 Objective Result；
- NX 输出 Measurement、ScalarField、RenderScene 和 TopologyMap，不执行规则；
- Hermes 完成 Evaluation、FailedPatch、三视角截图、Finding 和报告；
- 通过真实 NX E2E、PythonOCC 回归和同源 STEP/Parasolid Golden Model 验收。

完成标准：任一 Finding 能从报告反向追溯到图片、高亮三角形、场值、拓扑实体、Feature/
Region、Operation、规则、输入哈希和实现版本。

### M2.6-B：特征规则与指标逐项扩展

按工程价值逐项加入，不一次性实现候选清单。

推荐顺序：

1. 主壁、螺柱、筋等区域化壁厚和拔模角；
2. 根部 R 角；
3. 倒扣、滑块/斜顶相关区域；
4. 经工程评审批准的其它几何指标。

每个增量都必须同时交付 Recognizer/Region、Calculator、规则、证据、Golden Model 和工程
验收，不能只增加字段或报告文案。压铸等其它工艺必须建立独立 Scope 和认证范围，不复制
注塑阈值冒充支持。

### M2.6-C：黄金产品完整闭环

- 冻结真实或脱敏黄金产品、同源 STEP/Parasolid、确认事实和批准规则；
- 覆盖该产品全部批准指标；
- 生成不可变 Run Bundle；
- 由模具工程师人工核对 Measurement、区域、Finding、证据和报告并签字。

Ground Truth 只用于研发验收，不进入生产分析，也不回写运行结果。

### M3：二维图纸信息提取

- PDF/图片解析、OCR、版面和表格识别；
- 输出带页码、bbox、原文、单位和置信度的 Observation；
- 高置信度且无冲突的信息可转为 Fact，歧义进入 Clarification；
- 无可靠比例或明确标注时，不从像素推断精确几何尺寸。

### M4：二维工程特征与三维融合

- 识别公差、材料、表面要求、基准和局部工程标注；
- 将二维 Observation 与三维 Feature/Region 建立可审核 FusionLink；
- 冲突和低置信度映射由用户确认；
- 图纸信息参与规则选择，但不替代三维客观计算。

### M5：平台化与多工艺扩展

- 通用 Capability/Calculator 注册与认证；
- 受影响 Operation 重算和断点复用；
- 租户、项目、Run 和 Artifact 隔离；
- 新工艺通过 ProcessAdapter、独立事实和独立规则 Scope 接入；
- 生产部署、权限、审计、监控和容量验证。

## 4. 全阶段不变量

1. Manifest 是项目事实来源，聊天记录不是数据库。
2. 先发现后分析：冻结 DiscoverySnapshot 后才编译 AnalysisPlan。
3. Backend 只做特征识别和客观计算；Hermes 持有规则、Evaluation、证据和 Finding。
4. PythonOCC 与 NX 允许实现和精度不同，但数据契约与后处理流程必须一致。
5. 选择 NX Production 后禁止静默降级到 PythonOCC。
6. 未实现、低置信度或未认证能力必须显式阻塞或回退为 ordinary，不生成伪特征。
7. 修改规则只重做评价闭包；修改输入、拓扑、网格或算法版本会使相关客观缓存失效。
8. 新能力保持在 DFM toolset/服务边缘，不修改 Hermes Agent Loop，不增加无关会话工具负担。

## 5. 验收方式

| 层级 | 要求 |
| --- | --- |
| Contract | JSON Schema、共享 Fixture、跨 Run/输入/快照错配负例 |
| Component | Recognizer、Calculator、Rule、Evidence 各自行为测试 |
| Integration | 上传、Job、取消、失败恢复、Artifact 哈希和缓存恢复 |
| E2E | Desktop/CLI 创建项目到报告；PythonOCC STEP；真实 NX STEP/Parasolid |
| Engineering | 数值容差、问题区域重叠、截图可读性和模具工程师签字 |

## 6. 当前优先级

1. 与 NX 团队联合冻结 Schema 4/2 和共享 Fixture；
2. 实现 NX STEP/Parasolid Loader、Topology/RenderMesh Snapshot 和壁厚/拔模角 Calculator；
3. 实现第一批真实注塑 Feature/Region Recognizer；
4. 完成真实 NX 双格式 E2E 与 Golden Model 认证；
5. 在 M2.6-A 通过后逐项扩展特征和指标。

文档只记录已批准方向。字段和状态以 `tools/dfm/schemas/`、`tools/dfm/contracts.py` 和
`tools/dfm/scopes/` 为最终依据。
