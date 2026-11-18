# 配置

nas-mcp 使用一个 YAML 配置文件。默认读取工作目录下的 `config.yaml`，
也可以用 `uv run nas-mcp --config /path/to/config.yaml` 指定。

```bash
cp config.example.yaml config.yaml
chmod 600 config.yaml
```

`config.yaml` 含 M-Team API Key、access key 和 qBittorrent 凭据，已加入 `.gitignore`，
不要提交或打进镜像。旧版本的 `.env` 不再读取，请把原来的环境变量值迁移到对应字段。

## 完整示例

```yaml
adult_enabled: false

access_keys:
  - name: 日常助手
    key: "<access-key-1>"
    adult_enabled: false
  - name: 私人助手
    key: "<access-key-2>"
    adult_enabled: true
  - name: 跟随全局
    key: "<access-key-3>"
    adult_enabled: null

mcp:
  transport: streamable-http
  host: 127.0.0.1
  port: 8000

mteam:
  api_key: "<mteam-api-key>"
  api_base: https://api.m-team.cc/api
  site_url: https://kp.m-team.cc
  timeout: 30
  max_torrent_mb: 32

qbittorrent:
  url: "http://127.0.0.1:8080"
  basic_auth: ""
  username: ""
  password: ""
  save_path: ""
  category: ""
  tags: []
  timeout: 30

defaults:
  site: mteam
  downloader: qbittorrent
```

## 成人内容开关与 access key

`adult_enabled` 是全局默认值，默认 `false`，对所有 PT 站生效。

| 层级 | 值 | 行为 |
|---|---|---|
| 全局 | `true` | 默认允许搜索成人内容 |
| 全局 | `false` | 默认禁止搜索成人内容 |
| access key | `true` | 该 key 允许，覆盖全局值 |
| access key | `false` | 该 key 禁止，覆盖全局值 |
| access key | `null` 或省略 | 跟随全局值 |

关闭成人内容时：

- 请求中的成人分类会被删除，按剩余分类搜索；删除后没有剩余分类时，搜索普通分类。
- 上游返回的成人条目会被丢弃，不会出现在工具结果中。
- 不会返回“已禁用”或“权限不足”之类的提示，开关也不出现在工具参数和 `get_config_status` 中。

access key 只用于 HTTP 传输：

- 配置了 `access_keys` 后，所有 HTTP 请求必须携带 `Authorization: Bearer <key>`；
  缺失或无效返回 `401`。
- 未配置 `access_keys` 时不做客户端认证，使用全局 `adult_enabled`。
- stdio 模式不使用 access key，使用全局 `adult_enabled`。
- `name` 仅用于配置辨识，不会返回给模型。

客户端如何携带 Bearer key 见 [客户端接入](clients.md)。

## M-Team

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `mteam.api_key` | 是 | 无 | M-Team 存取令牌 |
| `mteam.api_base` | 否 | `https://api.m-team.cc/api` | API 根地址 |
| `mteam.site_url` | 否 | `https://kp.m-team.cc` | 站点域名，API 要求 Origin 一致 |
| `mteam.timeout` | 否 | `30` | HTTP 超时秒数 |
| `mteam.max_torrent_mb` | 否 | `32` | 单个种子最大大小（MB） |

API Key 获取位置：M-Team 控制台 → 实验室/API。

## qBittorrent

可使用 `qbittorrent.basic_auth` 对 WebUI 或其前置反向代理进行 HTTP Basic Auth；
若 qBittorrent WebUI 使用内置登录，则设置用户名和密码。

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `qbittorrent.url` | 是 | 无 | WebUI 地址，可省略 `http://` |
| `qbittorrent.basic_auth` | 否 | 无 | HTTP Basic Auth 凭据，格式为 `username:password`；设置后优先使用 |
| `qbittorrent.username` | 否 | 无 | 未设置 Basic Auth 时用于 qBittorrent WebUI 登录 |
| `qbittorrent.password` | 否 | 无 | 未设置 Basic Auth 时用于 qBittorrent WebUI 登录 |
| `qbittorrent.save_path` | 否 | 无 | 固定保存路径，设置后关闭 autoTMM |
| `qbittorrent.category` | 否 | 无 | 分类名，不存在时自动创建 |
| `qbittorrent.tags` | 否 | 无 | 标签列表，例如 `[pt, 4k]` |
| `qbittorrent.timeout` | 否 | `30` | HTTP 超时秒数 |

认证优先级：

1. 填写 `qbittorrent.basic_auth`：使用 `Authorization: Basic <credentials>`，不调用登录接口。
2. 未填写 Basic Auth，但设置了 `qbittorrent.username` 或 `qbittorrent.password`：
   调用 qBittorrent 登录接口并使用会话 Cookie。
3. 两种方式都未设置：假设 qBittorrent 已关闭本地认证。

## MCP 与默认项

| 字段 | 默认值 | 说明 |
|---|---|---|
| `mcp.transport` | `streamable-http` | `stdio` 或 `streamable-http` |
| `mcp.host` | `127.0.0.1` | HTTP 监听地址 |
| `mcp.port` | `8000` | HTTP 监听端口 |
| `defaults.site` | `mteam` | 默认 PT 站 |
| `defaults.downloader` | `qbittorrent` | 默认下载器 |

启动参数 `--config`、`--transport`、`--host`、`--port` 可以覆盖配置文件中的对应值。

## 安全说明

- `config.yaml` 不要提交。本地使用建议权限 `600`；Docker 部署时需确保容器用户可读。
- access key、M-Team API Key、qBittorrent 密码不会返回给模型，也不会写入日志。
- 未配置 `access_keys` 时 HTTP 服务没有客户端认证，远程访问必须自行加 HTTPS 和认证代理。
- M-Team 临时下载地址包含令牌，不返回给模型，也不记录日志。
- 下载种子时不会携带 `x-api-key`，避免跨域重定向泄露。
- qBittorrent 只添加任务，不提供删除、暂停等破坏性工具。
- 不提供“下载种子文件到本地”的工具，避免把 NAS 文件系统暴露给模型。
