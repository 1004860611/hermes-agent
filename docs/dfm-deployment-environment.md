# DFM 部署环境定义

本文定义 Hermes Agent 内建 DFM 能力的开发、测试与生产部署环境。目标是让同一套 DFM 代码在 Windows 本地开发、Linux/Docker 部署中保持一致，并避免长期依赖 Django 旧工程或 `aimold312` 等外部环境。

一次分析实际生成的输入副本、Run 日志、结构化结果、证据图片和 PPTX 位置，参见 [单次 DFM 分析数据说明](dfm-analysis-runbook.md)。

## 1. 当前支持范围

当前 M2.5 阶段的部署基线为：

- 工艺：注塑（`injection`）完整基线；压铸（`die_casting`）拓扑门。
- 三维输入：STEP/STP；Parasolid `x_t` 仅登记和能力诊断，Reader 仍未批准。
- 几何内核：OpenCascade，通过 `pythonocc-core` 使用。
- 报告：结构化 JSON、证据图片和 PPTX。
- 运行方式：Hermes 主进程创建 DFM 作业，几何分析在隔离 worker 子进程中执行。

二维图纸、OCR、更多制造工艺和独立远程计算服务属于后续扩展范围，不应作为当前部署成功的前置条件。

## 2. 运行架构

```text
Desktop / CLI / API
        |
        v
Hermes Agent
        |
        v
DFM Service -> Job Manager -> STEP Analyzer Worker
        |                         |
        |                         +-- pythonocc-core / OpenCascade
        |
        +-- artifacts / evidence / PPTX report
```

worker 与主进程通过版本化 JSON/JSONL 协议交换任务、进度、结果和错误。默认可使用同一个 Python 环境；也允许通过 `dfm.runtime.python` 指向独立的 OCC 环境。后一种方式适合解决 OpenCascade 与 Hermes 其他 Python 依赖的版本冲突。

## 3. 平台与版本基线

| 项目 | 开发/生产要求 |
| --- | --- |
| 操作系统 | Windows 10/11（开发）；Linux x86_64（Docker/生产） |
| Python | 3.11 或 3.12；仓库约束为 `>=3.11,<3.14` |
| Node.js | 使用仓库当前 Desktop workspace 所要求的版本 |
| 包管理 | Python 推荐 uv；安装 OCC 时使用 Conda/conda-forge |
| 几何内核 | `pythonocc-core`，来自 conda-forge |
| PPTX | `python-pptx==1.0.2`，由 `dfm` extra 管理 |
| 图片 | Pillow，由 Hermes 核心依赖管理 |
| 编码 | UTF-8 |

生产镜像必须锁定明确版本，不使用随时间漂移的 `latest` 依赖。

## 4. 依赖归属

### 4.1 pyproject.toml 管理的依赖

Hermes 和 DFM 的纯 Python 依赖由 `pyproject.toml` 与 `uv.lock` 管理。DFM 报告依赖通过 extra 安装：

```powershell
python -m pip install -e ".[dfm]"
```

使用 uv 时：

```powershell
uv sync --active --extra dfm --locked
```

`uv.lock` 用于固定可复现的 Python 依赖解析结果，不应删除。注意当前 `all` extra 不自动包含 `dfm`，部署时必须显式选择 `dfm`。

### 4.2 Conda 管理的依赖

`pythonocc-core` 包含原生 OpenCascade 库，目前不由 PyPI/uv 可靠提供，因此由 conda-forge 安装：

```powershell
conda install -n hermes-dev -c conda-forge pythonocc-core
```

CadQuery、VTK 和 FreeCAD 不是当前主分析路径的必需依赖。只有启用相应后续能力时才应加入部署环境。

## 5. Windows 本地开发环境

### 5.1 创建环境

```powershell
conda create -n hermes-dev -c conda-forge python=3.11 pythonocc-core pip
conda activate hermes-dev
python -m pip install -e ".[dfm]"
```

如果环境已经存在，则只需补齐 OCC 和项目依赖。

### 5.2 VS Code 调试

`.vscode/launch.json` 应明确使用：

```text
E:\conda_envs\hermes-dev\python.exe
```

建议调试进程设置 UTF-8：

```json
{
  "PYTHONUTF8": "1",
  "PYTHONIOENCODING": "utf-8"
}
```

这可以避免 Windows 默认 GBK 解码 worker 输出时触发 `UnicodeDecodeError`。代码仍应在创建子进程时显式指定 UTF-8，环境变量只作为部署保护。

### 5.3 启动

后端：

```powershell
python .\hermes serve --host 127.0.0.1 --port 9120
```

Desktop：

```powershell
npm install
npm run dev --workspace apps/desktop
```

Desktop 是独立 Electron 前端，连接 `hermes serve` 暴露的 JSON-RPC/API 后端；不需要额外启动 Dashboard。

## 6. DFM 配置

行为配置写入 `~/.hermes/config.yaml`，不写入 `.env`。推荐初始配置：

```yaml
dfm:
  runtime:
    python: auto
    max_concurrent_runs: 1
    timeout_seconds: 900
  intake:
    max_file_size_mb: 200
    max_pages: 50
  defaults:
    process: injection
  nx:
    # Optional remote-only Siemens NX compute backend. There is no local fallback.
    endpoint: ""
    request_timeout_seconds: 30
    poll_interval_seconds: 2
  evidence:
    max_rendered_findings: 12
  retention:
    keep_failed_runs: true
```

配置 `dfm.nx.endpoint` 后，Parasolid `.x_t` 通过 HTTP NX Backend 执行；未配置时
返回 `dependency_missing`，不会尝试本地启动 NX。认证 Token 是机密，通过
`NX_BACKEND_TOKEN` 提供，不写入 `config.yaml`。完整 Server/C++ 插件协议见
[NX HTTP Backend 契约](plans/2026-07-23-dfm-nx-http-backend-contract.md)。
NX Server 和 C++ 插件开发团队应以
[NX Server 与 NX C++ 插件开发交接规格](plans/2026-07-23-nx-server-plugin-development-spec.md)
作为实施与验收清单。

- `runtime.python: auto`：worker 使用当前 Hermes Python 解释器。
- `runtime.python: /absolute/path/to/python`：worker 使用独立 DFM/OCC 环境。
- `max_concurrent_runs`：单机并发作业数。OCC 分析占用 CPU 和内存，初始建议为 1。
- `timeout_seconds`：单次分析超时。
- `keep_failed_runs`：保留失败作业的中间产物和日志，便于诊断。

API key、session token 等秘密信息才放在 `~/.hermes/.env`，且不得写入镜像或 Git。

## 7. Docker 生产环境

当前推荐单容器部署：Hermes、DFM worker 和 OCC 位于同一镜像，worker 仍以子进程隔离。这样部署简单，同时保留未来拆分独立 worker 服务的协议边界。

参考 Dockerfile：

```dockerfile
ARG BASE_IMAGE=continuumio/miniconda3:24.11.1-0
FROM ${BASE_IMAGE}

WORKDIR /app
COPY . /app

RUN conda install -y -c conda-forge python=3.11 pythonocc-core \
    && conda clean -afy \
    && python -m pip install --no-cache-dir ".[dfm,web]"

ENV PYTHONUTF8=1
ENV PYTHONIOENCODING=utf-8
ENV HERMES_HOME=/data/hermes

EXPOSE 9120
VOLUME ["/data/hermes"]

CMD ["python", "./hermes", "serve", "--host", "0.0.0.0", "--port", "9120"]
```

正式镜像应进一步：

- 将基础镜像固定到具体 tag 或 digest。
- 使用 `uv.lock`/约束文件保证 Python 依赖可复现。
- 使用非 root 用户运行。
- 为 `/data/hermes` 和 DFM artifact 目录配置持久卷。
- 根据 STEP 文件规模设置 CPU、内存和临时磁盘限制。
- 通过 secrets 注入凭据，不将 `.env` 打入镜像。
- 配置健康检查和作业超时。

Linux 容器内不得写死 Windows 路径。保持 `runtime.python: auto`，或填写容器内绝对路径（例如 `/opt/conda/bin/python`）。

## 8. 环境验证

### 8.1 依赖自检

```powershell
python -c "from OCC.Core.BRep import BRep_Tool; print('OCC OK')"
python -c "import pptx; from PIL import Image; print('Report dependencies OK')"
python -m pip check
```

### 8.2 Hermes DFM 自检

```powershell
python .\hermes dfm doctor --json
```

应重点确认：

- `runtime.python_executable` 指向预期解释器。
- OCC 和 PPTX 依赖状态正常。
- STEP 分析、证据生成、报告生成能力处于可用状态。

### 8.3 E2E 验收

部署环境只有在真实链路通过后才算合格：

1. 启动 `hermes serve`。
2. Desktop 成功连接后端，无 401 和连接超时。
3. 上传一份已知可解析的 STEP 样件。
4. 确认材料、拔模方向和模型单位的澄清问题后创建 injection DFM Plan。
5. 页面持续收到阶段、进度或心跳，不应长时间无反馈。
6. 作业完成并生成结构化结果、项目级 Finding、PNG 证据、高亮 STEP 和报告。
7. 每个重点问题最多包含正视、剖视、斜视三张证据图。
8. PPTX 报告可打开，问题、指标和证据图片能正确对应。
9. 用同名 STEP 的新版本或修改拔模方向验证旧 Plan 失效，并从该 Plan 生成受影响 operation 的最小重跑计划。
10. 取消、超时和分析异常能回写明确状态及错误信息。

## 9. 日志与故障定位

Hermes 日志位于 `~/.hermes/logs/`，可使用：

```powershell
hermes logs --follow
```

常见问题：

| 现象 | 检查项 |
| --- | --- |
| `ModuleNotFoundError: OCC` | 实际启动解释器是否为安装了 `pythonocc-core` 的 Conda 环境 |
| `ModuleNotFoundError: pptx` | 是否安装 `.[dfm]` 或执行 `uv sync --extra dfm` |
| GBK `UnicodeDecodeError` | 父进程/worker 是否显式使用 UTF-8，VS Code 是否选中正确解释器 |
| Desktop 连接超时 | 9120 端口、后端进程、Desktop backend URL 是否一致 |
| 401 Unauthorized | Desktop 与后端 session token 是否来自同一次启动/同一配置 |
| 分析长时间无反馈 | worker 日志、心跳、超时、作业状态和 artifact 目录 |
| Docker 中找不到文件 | 上传文件是否写入双方可见的持久卷，路径是否为容器内路径 |

## 10. 发布前检查清单

- Python、OCC 和 PPTX 版本已固定。
- `uv.lock` 与 `pyproject.toml` 同步。
- Docker 镜像不包含本机路径、token 或 API key。
- Windows 开发环境和 Linux Docker 环境均通过 `dfm doctor`。
- 至少一个基准 STEP 完成 E2E，并校验证据图与 PPTX。
- 大文件、超时、取消和失败保留策略已验证。
- artifact 目录容量、清理和备份策略已配置。
- 当前完整声明 injection/STEP；die_casting/STEP 只声明拓扑门；Parasolid `x_t` 明确声明为未实现能力，未实现能力不会被误报为可用。

## 11. 后续演进

当计算量或并发要求增长时，可将 STEP Analyzer worker 拆为独立 DFM 计算服务。拆分时应继续复用现有任务契约、进度事件、取消、超时和 artifact 描述，不让 Agent 或 Desktop 直接依赖 OpenCascade。新增工艺通过 ProcessAdapter 和规则/指标配置扩展，部署层只声明实际安装且通过自检的能力。
