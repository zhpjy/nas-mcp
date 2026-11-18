# nas-mcp

面向 NAS 的 MCP 服务：让 AI 搜索 PT 站种子、推送到 qBittorrent，并查看下载进度。

当前支持：

- PT 站：M-Team（官方 API）
- 下载器：qBittorrent 4.x / 5.x（WebUI API）
- HTTP access key：每个 key 可单独设置成人内容权限，默认不启用成人内容

## 快速开始（Docker）

需要 Docker 和 Docker Compose。

```bash
git clone https://github.com/zhpjy/nas-mcp.git
cd nas-mcp
cp config.example.yaml config.yaml
chmod 644 config.yaml   # 容器内以 uid 10001 运行，需要可读
# 编辑 config.yaml，填入 mteam.api_key 和 qbittorrent 配置
docker compose up -d --build
docker compose exec nas-mcp nas-mcp --check
```

`compose.yaml` 以 `streamable-http` 监听容器内 `0.0.0.0:8000`，默认只映射到宿主机
`127.0.0.1:8000`，客户端连接 `http://127.0.0.1:8000/mcp`。需要局域网直连或使用已发布镜像时，
见 [Docker 部署](docs/deployment.md)。

qBittorrent 在宿主机上时，`qbittorrent.url` 要填 `http://host.docker.internal:8080`；
容器内的 `127.0.0.1` 指容器自身。

`--check` 会检查配置并尝试连接 M-Team 和 qBittorrent。

## 用 uvx 运行

不克隆源码也可以运行。推送 `v*` 标签时，GitHub Actions 会构建 wheel 和 sdist
并挂到 GitHub Release，用 `uvx` 直接安装：

```bash
uvx --from https://github.com/zhpjy/nas-mcp/releases/download/v0.2.4/nas_mcp-0.2.4-py3-none-any.whl \
  nas-mcp --check
```

也可以从 Git 源码运行（需要本机有 `git`）：

```bash
uvx --from git+https://github.com/zhpjy/nas-mcp nas-mcp --transport stdio
```

`uvx` 会在任意工作目录启动，配置文件按以下顺序查找：

1. `--config /path/to/config.yaml`
2. `NAS_MCP_CONFIG` 环境变量
3. 当前目录的 `config.yaml`
4. `~/.config/nas-mcp/config.yaml`（设置了 `XDG_CONFIG_HOME` 时为 `$XDG_CONFIG_HOME/nas-mcp/config.yaml`）

uvx 场景建议把配置放到用户目录：

```bash
mkdir -p ~/.config/nas-mcp
cp config.example.yaml ~/.config/nas-mcp/config.yaml
chmod 600 ~/.config/nas-mcp/config.yaml
# 编辑 ~/.config/nas-mcp/config.yaml，填入 mteam.api_key 和 qbittorrent 配置
```

也可以完全不用配置文件，直接用环境变量（适合交给客户端或 magpie 托管）：

```bash
export NAS_MCP_MTEAM_API_KEY="<mteam-api-key>"
export NAS_MCP_QBITTORRENT_URL="http://192.168.1.10:8080"
export NAS_MCP_QBITTORRENT_USERNAME="admin"
export NAS_MCP_QBITTORRENT_PASSWORD="<password>"
uvx --from https://github.com/zhpjy/nas-mcp/releases/download/v0.2.4/nas_mcp-0.2.4-py3-none-any.whl \
  nas-mcp --transport stdio
```

环境变量会覆盖配置文件中的同名字段，完整列表见 [配置](docs/configuration.md#环境变量)。

`uvx nas-mcp` 默认是 `streamable-http`；本地 MCP 客户端需要 stdio 时加 `--transport stdio`。
升级时把命令中的版本号换成新版本。

## 本地运行（uv）

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```bash
uv sync
cp config.example.yaml config.yaml
chmod 600 config.yaml
# 编辑 config.yaml，填入 mteam.api_key 和 qbittorrent 配置
uv run nas-mcp --check
uv run nas-mcp
```

默认使用 `streamable-http`，客户端连接 `http://<host>:8000/mcp`。配置了 `access_keys` 后，HTTP 请求需要携带
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
