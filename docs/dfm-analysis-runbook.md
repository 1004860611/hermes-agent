# DFM 分析运行手册（OCCT）

## 当前能力

- 三维输入：单实体 B-Rep 的 STEP/STP。
- 工艺：首版仅支持 `injection`。
- 几何内核：独立的 Windows C++17 `dfm-geometry.exe`，动态链接 Analysis Situs
  v2025.2 与 OCCT 7.9.3。
- 分析器：`analyzer_key=occt`。
- 成熟度：全部算法为 `experimental`；计划时必须显式传入
  `verification_level=experimental`，不会从 certified 静默降级。
- 客观能力：STEP/BRep preflight、稳定拓扑索引、Analysis Situs AAG、拔模、
  滚球壁厚、倒扣、锐角，以及钻孔、圆角链、轴、任意型腔、凸包面、孤立特征、
  规范曲面、曲面探针、倒角和加强筋识别。
- 拔模采用锁定版 FreeCAD DFM 的平面中心/曲面 20x20 UV 法线采样；壁厚采用
  `SphereThicknessAnalyzer` 滚球法，同时输出最小 `thickness_mm` 和算术平均
  `average_thickness_mm`。材料不参与这两项几何计算。

## 标准流程

1. `dfm_project(create)` 创建持久项目。
2. `dfm_project(add_input)` 登记 STEP/STP；intake 只执行快速语法预检，OCCT
   worker 才是 B-Rep 权威。
3. `dfm_project(status)` 检查 `occt` capability。
4. 按 clarification 让用户确认模型单位；拉模方向可以由用户确认，未确认时
   计划固定使用 `+Z` 并写入 `assumed_pull_direction=true`。
5. `dfm_analysis(plan, analyzer_key="occt",
   verification_level="experimental")`；检查 input hash、scope
   `injection.geometry-core@4.0.0` 和操作 DAG。
6. 仅在 capability 为 `available` 时 `start`，保存并复用返回的 `run_id`。
7. 运行成功后读取 `measurements.json`、`features.json`、`topology.json`、
   `preflight.json`、Hermes evaluations/findings 和报告。

## 进度、超时与取消

- `objective_compute` 25% 表示正在构建 AAG；拓扑完成后会进入
  `topology_ready`，随后依次显示 `measure_draft`、
  `measure_wall_thickness`、`measure_undercut`、
  `measure_sharp_corner` 和 `recognize_features`。完成百分比保持单调递增。
- 复杂 STEP 在单个测量阶段停留数分钟属于允许行为。只要运行仍是
  `running` 且尚未达到 `dfm.geometry.timeout_seconds`，不能仅凭百分比未变化
  判断 Hermes 断开或 OCCT 死锁，也不要直接 `taskkill` 原生进程。
- 在配置超时前，只有用户明确要求停止时才调用
  `dfm_analysis(action="cancel", confirm_cancel=true)`。未确认的提前取消返回
  `cancel_confirmation_required`，运行继续保留。
- 滚球壁厚为整个模型复用一次 OCCT 距离极值器；法向射线只初始化球半径上界，
  最终结果始终是迭代收缩后的球直径。初始射线、距离极值查询和原生时间均有
  确定预算。超限分别返回
  `geometry_operation_budget_exceeded` 或 `geometry_operation_timeout`，不会无限
  运行或用不完整数据生成测量结果。

## 完整性边界

几何引擎只产生事实、测量有效性、质量诊断和拓扑引用。规则、阈值、Evaluation、
Finding 及报告由 Hermes 持有。当前注塑几何计划不要求材料；不得从外观推断单位
或客户标准，也不得把 experimental 结果描述为 certified。平均壁厚没有规则绑定，
因此只作为测量事实入库，不单独产生 finding。

STEP 中的长度单位由 OCCT 读取并记录；毫米、厘米、米、英寸和英尺输入都统一输出
毫米。用户确认的 `model_units` 同时保留在计划/preflight 诊断中，不能覆盖文件自身
的单位元数据。

执行失败时保留 project/run ID，并检查状态返回的 events/stdout/stderr 路径。
`geometry_engine_missing` 使用 `hermes dfm doctor` 检查可执行文件；不得自动安装系统依赖。
