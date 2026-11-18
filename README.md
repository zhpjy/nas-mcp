# nas-mcp

面向 NAS 的 MCP 服务：让 AI 搜索 PT 站种子、推送到 qBittorrent，并查看下载进度。

当前支持：

- PT 站：M-Team（官方 API）
- 下载器：qBittorrent 4.x / 5.x（WebUI API）
- HTTP access key：每个 key 可单独设置成人内容权限，默认不启用成人内容

## 快速开始

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```bash
uv sync
cp config.example.yaml config.yaml
chmod 600 config.yaml
# 编辑 config.yaml，填入 mteam.api_key 和 qbittorrent 配置
uv run nas-mcp --check
```

默认读取工作目录下的 `config.yaml`，也可以用 `--config /path/to/config.yaml` 指定。
`--check` 会检查配置并尝试连接 M-Team 和 qBittorrent。

## 运行

默认使用 `streamable-http`：

```bash
uv run nas-mcp
```

客户端连接 `http://<host>:8000/mcp`。配置了 `access_keys` 后，HTTP 请求需要携带
`Authorization: Bearer <access-key>`；未配置时不做客户端认证，远程访问请自行加认证和网络隔离。

本地客户端需要 stdio 时：

```bash
uv run nas-mcp --transport stdio
```

## 在 opencode 中使用

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "nas-mcp": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "--directory",
        "/path/to/nas-mcp",
        "nas-mcp",
        "--transport",
        "stdio"
      ],
      "enabled": true
    }
  }
}
```

HTTP、Claude Desktop 等接入方式见 [客户端接入](docs/clients.md)。

## 文档

- [配置](docs/configuration.md)：`config.yaml` 全部字段、成人内容开关与 access key
- [工具与工作流](docs/tools.md)
- [客户端接入](docs/clients.md)
- [Docker 部署](docs/deployment.md)
- [开发](docs/development.md)
