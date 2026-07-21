# DFM M1.2 指标拆解实施记录

M1.2 的目标是把整体迁入的 STEP 分析器拆为可审计的执行链：

`共享 STEP 索引 → 检查族 → Measurement → Evaluation → 兼容 Issue → Evidence/Report`

## 已落地

- `GeometryRef`、`MeasurementRecord`、`EvaluationRecord` 契约；
- `LoadedStepModel`：每次 Run 一次性建立 bbox、拓扑、面和边索引；
- `legacy_issue_catalog_v1.json`：覆盖当前所有 legacy issue code、检查族、主指标和参数引用；
- 粗粒度 scope 拆为 topology、small features、planar spacing、face quality、cylindrical、thickness、draft、continuity、undercut 和 evidence operations；
- worker 只接受依赖有序的白名单 operation，并执行持久化 Plan 中实际列出的检查族；
- `measurements.json`：与旧报告并行保存，不改变现有 JSON/Markdown/PPTX/STEP 交付；
- evidence pipeline 与几何检查分离，未选择 `render_evidence` 时不生成图片或高亮 STEP；
- 小特征、平面拔模、平面间距、面质量、圆柱特征、厚度场、连续性和倒扣/侧抽主算法均已迁入独立 `checks/` 模块；
- 证据渲染与高亮 STEP 主入口已迁入 `evidence/`，兼容 JSON/Markdown 报告入口已迁入 `reporting/legacy_reports.py`；
- Windows manifest 原子替换增加短暂 reader/杀毒锁重试，避免高频 artifact 事件放大偶发写入失败。

## 保持的不变量

- 默认 legacy baseline scope 的 issue 关系和数值与迁移来源等价；
- Plan 未选择的检查族不产生对应问题或 evidence 副作用；
- Measurement 不由 LLM 产生，并绑定输入哈希和算法版本；
- 参数保留来源，并区分 `rule`、`algorithm` 和 `engineering_context`；
- 旧报告制品继续作为兼容交付，M1.2 不提前实现 M6 规则库或新严重度算法。

## 完成判据

- compatibility 文件不再拥有检查族、证据或兼容报告主入口；
- 每个持久化 operation 可独立执行，且只产生所属检查族的问题；
- 默认全量 scope 与迁移来源保持 issue 关系和数值等价；
- worker 结果必须引用且登记唯一 `measurements.json`；
- 完整 DFM 测试矩阵、Ruff 和 `git diff --check` 通过。
