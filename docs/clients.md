# 客户端接入

服务默认使用 `streamable-http`，本地 stdio 或远程 HTTP 都可以接入。
配置项见 [配置](configuration.md)。

## opencode：本地 stdio

`uv --directory` 会把工作目录切到项目目录，因此会读取该目录下的 `config.yaml`：

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

stdio 不使用 access key，成人内容权限取全局 `adult_enabled`。

## opencode：HTTP

先启动服务：

```bash
uv run nas-mcp
```

远程访问时用 `--host 0.0.0.0`，或在 `config.yaml` 中设置 `mcp.host`。
客户端连接 `http://<host>:8000/mcp`。配置了 `access_keys` 后需要携带对应 key：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "nas-mcp": {
      "type": "remote",
      "url": "http://<NAS-IP>:8000/mcp",
      "headers": {
        "Authorization": "Bearer <access-key>"
      },
      "enabled": true
    }
  }
}
```

未配置 `access_keys` 时不需要 `headers`，但服务也没有客户端认证；
远程暴露时应在前面配置 HTTPS 和认证代理。

## Claude Desktop：本地 stdio

```json
{
  "mcpServers": {
    "nas-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/nas-mcp",
        "nas-mcp",
        "--config",
        "/path/to/nas-mcp/config.yaml",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

## 启动参数

```bash
uv run nas-mcp --help
```

- `--config`：配置文件路径，默认 `config.yaml`
- `--transport`：`stdio` 或 `streamable-http`
- `--host`：覆盖 `mcp.host`
- `--port`：覆盖 `mcp.port`

Docker 方式见 [Docker 部署](deployment.md)。
