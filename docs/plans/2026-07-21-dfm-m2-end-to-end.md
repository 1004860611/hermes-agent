# DFM M2 STEP 端到端闭环实施记录

## 目标与边界

M2 只交付注塑 STEP/STP 产品零件的真实闭环：输入、澄清、计划、运行、恢复、证据和报告。继续复用 Hermes 的 Agent Loop、附件、后台任务和 Artifacts，不引入新的核心工具或第二套 Desktop 聊天界面；2D/OCR、混合输入融合、其他制造工艺和 SimpleCADAPI 不属于 M2。

## 工作包

1. **输入预检**：校验 ISO 10303-21 magic/区段、B-Rep 声明、基础实体可读性、文件大小和复杂度摘要；失败发生在 OCC worker 启动前，且不留下未登记副本。
2. **澄清与计划门控**：STEP 分析必须确认材料、拔模方向和模型单位。问题、答案和 Fact 持久化到 Manifest；Plan 参数保留来源，未确认时返回 `clarification_required`。
3. **Finding 归一化**：从 M1.2 Measurement/Evaluation 和版本化 issue catalog 生成稳定 Finding ID、规则引用和 evidence 引用；旧 JSON/Markdown/PPTX 报告继续作为兼容制品。
4. **版本与恢复**：新增输入或修改确认事实后旧 Plan 标记 `invalidated`；既有 Run 保留原 Plan 快照。补充输入版本关系、受影响 operation 计算和幂等重跑。
5. **用户闭环**：验证 Desktop 附件到 intake、后台进度、取消/恢复、Artifacts 发现、证据和报告打开；CLI 以现有工具调用和 `hermes dfm doctor` 为诊断入口。
6. **交付与运维**：补齐 OpenCascade/runtime Python 安装、容器配置、示例、故障排查和可复现性验收记录。

## 实施顺序

```text
输入预检 -> 澄清门控 -> 稳定 Plan
                        -> Measurement/Evaluation -> Finding/Evidence
输入/事实版本 -> Plan 失效 -> 受影响步骤重跑
上述领域链路 -> Desktop/CLI 验收 -> 部署文档
```

## 当前进度

- 已实现第一批输入预检：真实 STEP 格式、B-Rep 表示声明、实体数量和复杂度摘要。
- 已实现材料、拔模方向、模型单位的持久化澄清门控。
- 已实现新增输入/确认事实后的 Plan 失效，旧 Run 快照不变。
- 已实现 Measurement/Evaluation 到项目级 Finding 的稳定归一化，并引用原始测量、报告、PNG 证据与高亮 STEP；兼容报告保持只读。
- 已实现输入版本谱系：同名同类型新输入显式替代旧输入，后续 Plan 仅引用活动版本；失效 Plan 记录原因和受影响 operation，`plan(base_plan_id=...)` 生成依赖闭包的最小重跑计划。
- 待实现完整 Desktop/部署验收。

## M2 完成证据

- 单元/契约测试覆盖输入拒绝无残留、澄清恢复、参数 provenance、Plan 失效和旧 Run 可追溯。
- OCC 真实夹具 E2E 覆盖上传、计划、启动、取消/恢复、结构化 Finding、PNG/高亮 STEP/报告导出。
- 同一输入哈希、事实、Plan、worker 和 scope 版本重复运行得到等价 Measurement、Evaluation 和 Finding。
- Desktop 实测证明附件、进度和 Artifacts 闭环，失败时不影响普通聊天。
- DFM 测试矩阵、Ruff 和 `git diff --check` 通过。

## 验收结果

- `pytest tests/tools/dfm tests/hermes_cli/test_dfm_command.py tests/tui_gateway/test_dfm_background_progress.py -q`：`130 passed`。
- 真实 OCC STEP 端到端用例覆盖上传、澄清、Plan、后台 Run、Measurement/Evaluation、Finding 和报告制品。
- Desktop Artifacts UI 用例：`6 passed`，覆盖 DFM JSON 与 PPTX 从工具结果到文件打开路径的发现。
- `ruff check tools/dfm tests/tools/dfm tests/hermes_cli/test_dfm_command.py tests/tui_gateway/test_dfm_background_progress.py` 与 `git diff --check` 均通过。
