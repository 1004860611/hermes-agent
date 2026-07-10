# Gateway、Dashboard 和 Desktop 的关系

本文说明 Hermes 中 `gateway`、`dashboard`、`desktop` 三者的职责、进程关系、接口边界和数据权限边界，尤其用于酒店系统 `hermesConsumer` 集成场景。

## 一句话总结

```text
gateway   = 面向外部业务系统/消息平台的集成入口
dashboard = 面向本机管理和 Hermes Web UI 的后端服务
desktop   = Electron 桌面壳，连接 dashboard 后端
```

三者可以共用同一个 `HERMES_HOME`、`config.yaml`、`.env` 和模型配置，但它们不是同一个进程，也不是同一种安全边界。

## 进程关系

### Gateway

启动命令通常是：

```bash
hermes gateway run
```

主要代码：

```text
gateway/run.py
gateway/platforms/api_server.py
```

在酒店系统集成里，`hermesConsumer` 调用的是 gateway 的 enterprise API：

```text
POST /v1/enterprise/turn/stream
```

这条链路会读取 enterprise contract：

```json
{
  "user": { "id": "...", "type": "..." },
  "session": { "id": "..." },
  "runtimePolicy": { "allowedCapabilityRefs": [...] },
  "credentialBroker": { "credentialRef": "...", "scope": [...] }
}
```

然后按 `user.id` 定位用户工作空间。

### Dashboard

启动命令通常是：

```bash
hermes dashboard --no-open --host 127.0.0.1 --port 3000 --insecure
```

主要代码：

```text
hermes_cli/web_server.py
```

Dashboard 是 Web/API/WS 后端，提供：

```text
/api/status
/api/ws
/api/pty
/api/sessions
/api/config
...
```

它不是专门给酒店业务系统调用的 enterprise API，而是 Hermes 自己的管理 UI / Web UI / Desktop 后端。

Dashboard 可以观察或管理 gateway 状态，例如 `/api/status` 里可能返回：

```json
{
  "gateway_running": true,
  "gateway_pid": 20292,
  "hermes_home": "C:\\Users\\lenovo\\.hermes"
}
```

这表示 dashboard 看到了 gateway 进程，但不表示 dashboard 的聊天能力全部依赖 gateway 提供。

### Desktop

启动命令通常是：

```bash
npm run dev --workspace apps/desktop
```

主要代码：

```text
apps/desktop/electron/main.cjs
apps/desktop/src/
```

Desktop 是 Electron 桌面客户端。它不直接调用 gateway 的 enterprise API，而是连接 dashboard 后端：

```text
desktop -> dashboard /api/ws
desktop -> dashboard /api/sessions
desktop -> dashboard /api/pty
```

开发时如果已经手动启动 dashboard，可以让 desktop 连接已有 dashboard：

```powershell
$env:HERMES_DESKTOP_REMOTE_URL="http://127.0.0.1:3000"
$env:HERMES_DESKTOP_REMOTE_TOKEN="hello-hermes-dashboard"

npm run dev --workspace apps/desktop
```

对应 dashboard 需要使用相同 token：

```powershell
$env:HERMES_DASHBOARD_SESSION_TOKEN="hello-hermes-dashboard"
hermes dashboard --no-open --host 127.0.0.1 --port 3000 --insecure
```

注意：`HERMES_DESKTOP_REMOTE_TOKEN` 对应的是 dashboard 的 `HERMES_DASHBOARD_SESSION_TOKEN`，不是 `API_SERVER_KEY`，也不是 `HERMES_ENTERPRISE_API_KEY`。

## 数据空间

Gateway enterprise API 为酒店用户做了用户工作空间隔离。

普通 Hermes / dashboard 默认数据通常在：

```text
<HERMES_HOME>/state.db
<HERMES_HOME>/memory/
```

酒店 enterprise 用户数据通常在：

```text
<HERMES_HOME>/enterprise/users/<user_id>/state.db
<HERMES_HOME>/enterprise/users/<user_id>/memory/
<HERMES_HOME>/enterprise/users/<user_id>/workspace/
```

例如本地：

```text
C:\Users\lenovo\.hermes\enterprise\users\<user_id>\state.db
```

服务器测试环境可能是：

```text
/opt/hermes-data-test/enterprise/users/<user_id>/state.db
```

## 权限边界

### Gateway enterprise API 的边界

酒店系统应通过 gateway enterprise API 调用 Hermes：

```text
consumer -> gateway /v1/enterprise/turn/stream
```

这条链路的权限边界较窄：

```text
user.id 决定用户工作空间
session.id 决定该用户下的会话
allowedCapabilityRefs 决定本轮可用工具
credentialRef 决定本轮能否回调酒店系统
```

普通用户通过接口层只能访问自己的 workspace，不会天然读取其它用户的会话数据。

管理员是否能跨用户查询，需要额外实现专门的 enterprise admin API；当前普通 turn 接口不会自动让管理员看到所有用户。

### Dashboard 的边界

Dashboard 权限更大，因为它是本机管理后端。

如果 dashboard 运行账号可以读取：

```text
<HERMES_HOME>/enterprise/users/*
```

并且 dashboard 会话开放了文件/终端等泛化工具，那么从能力上讲，dashboard agent 可以被提示去读取这些文件。

因此：

```text
dashboard 不是多租户安全边界
```

Dashboard 适合：

```text
- 本机开发调试
- 管理员操作
- 查看和修改 Hermes 配置
- 管理模型、工具、日志、普通会话
```

不适合：

```text
- 暴露给酒店普通用户
- 作为酒店业务用户正式对话入口
- 承载多租户安全隔离
```

## 为什么酒店系统不建议直接调 Dashboard

Dashboard 已经有一些会话查询、历史查看、配置管理能力，但这些接口是为 Hermes UI 设计的，不是为酒店业务系统的 `user.id/session.id/credentialRef` 安全模型设计的。

酒店系统直接调用 dashboard `/api/sessions` 这类接口，会遇到几个问题：

```text
1. 不天然理解酒店 user.id/session.id
2. 不天然执行 credentialRef scope 校验
3. 不天然按酒店 staff/user/admin 做业务权限隔离
4. 容易把 dashboard 的本机管理员能力暴露给普通业务用户
```

更好的做法是：

```text
酒店业务系统 -> gateway enterprise API
```

如果酒店系统需要查询、删除、重命名历史会话，应在 gateway enterprise API 下新增专门接口，底层复用 `SessionDB` 和 `EnterpriseWorkspaceManager`：

```text
GET    /v1/enterprise/sessions
GET    /v1/enterprise/sessions/{session_id}/messages
PATCH  /v1/enterprise/sessions/{session_id}
DELETE /v1/enterprise/sessions/{session_id}
POST   /v1/enterprise/sessions/{session_id}/fork
```

这样可以复用 dashboard 底层能力，但仍然保持 gateway enterprise 的安全边界。

## 推荐部署方式

### 酒店业务系统

```text
hotel frontend/backend
  -> hermesConsumer
  -> gateway /v1/enterprise/turn/stream
```

只开放受控工具：

```text
hotel_search
order_search
order_* diagnostic tools
resolver_*
memory
session_search
clarify
```

不要给普通酒店用户开放：

```text
terminal
read_file
write_file
patch
browser
```

### 管理/开发

```text
developer/admin
  -> dashboard
  -> desktop 或 web dashboard
```

Dashboard 应仅限管理员或内网开发环境使用。

生产环境如果要启用 dashboard，建议：

```text
- 只绑定 localhost 或内网
- 加强访问控制
- 不暴露给普通酒店业务用户
- 必要时与 gateway 分离 HERMES_HOME 或系统账号
```

## 本地开发常用命令

启动 gateway enterprise API：

```powershell
$env:HERMES_HOME="C:\Users\lenovo\.hermes"
$env:API_SERVER_ENABLED="true"
$env:API_SERVER_KEY="dev-secret-change-me"

hermes gateway run
```

启动 dashboard：

```powershell
$env:HERMES_HOME="C:\Users\lenovo\.hermes"
$env:HERMES_DASHBOARD_SESSION_TOKEN="hello-hermes-dashboard"

hermes dashboard --no-open --host 127.0.0.1 --port 3000 --insecure
```

启动 desktop 并连接已有 dashboard：

```powershell
$env:HERMES_DESKTOP_REMOTE_URL="http://127.0.0.1:3000"
$env:HERMES_DESKTOP_REMOTE_TOKEN="hello-hermes-dashboard"

npm run dev --workspace apps/desktop
```

