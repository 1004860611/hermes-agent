# DFM OCCT Windows 部署

## 运行形态

Hermes 主进程不加载 CAD DLL。`OcctAnalyzer` 通过参数数组启动本地
`dfm-geometry.exe`，request 使用 JSON 文件，stdout 只接收 JSONL 事件，artifact
写入当前 run 的受控目录。几何进程超时或取消时由现有 ProcessRunner 终止进程树。

## 构建

几何源码由 `B25004Y-Mould-project` 仓库的 `dfm-occt-worker` 分支维护，目录为
`DFMAnalysis_OCCT/`。Hermes 仓库不跟踪该源码；Windows 开发环境使用目录联接将
`dfm-geometry/` 指向外部仓库中的 `DFMAnalysis_OCCT/`。因此全新检出 Hermes 时，
需要先单独检出外部仓库并创建联接。标准环境为 VS2022 x64、CMake 3.24+ 和锁定的
vcpkg manifest。标准依赖固定为Analysis Situs `v2025.2`（源码随项目锁定并针对相同 ABI 编译）和 OCCT
`7.9.3#1`；也可使用 `OpenCASCADE_DIR` 指向已有的 7.9.3 安装。
标准 CI 仍使用 VS2022；本地 VS2026 可通过
`windows-vcpkg-vs2026-ninja-release` 预设和 VS 自带 CMake/Ninja 构建。

## 配置

行为配置只进入 `~/.hermes/config.yaml`：

```yaml
dfm:
  geometry:
    executable: dfm-geometry/out/install/windows-vcpkg-vs2026-sln/bin/dfm-geometry.exe
    timeout_seconds: 900
```

相对 `executable` 固定以当前 Hermes 源码根目录解析，不受桌面启动目录或项目目录
影响。若省略 `executable`，按仓内标准 install/build 目录及 PATH 顺序发现。不得为
这些设置新增 `.env` 变量。

运行：

```powershell
hermes dfm doctor --json
```

doctor 报告 executable、engine version、OCCT capability 和 experimental 状态，
但不会安装依赖。
