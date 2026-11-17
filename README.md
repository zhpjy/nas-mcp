# nas-mcp

面向 NAS 的 MCP 服务：让 AI 搜索 PT 站种子、推送到 qBittorrent，并查看下载进度。

当前支持：

- PT 站：M-Team（官方 API）
- 下载器：qBittorrent 4.x / 5.x（WebUI API）

后续可通过 `PTProvider` / `Downloader` 抽象增加更多站点和下载器，MCP 工具保持不变。

## 设计原则

- **不向 AI 暴露文件**：种子只在服务端内存中流转，直接上传 qBittorrent，不落盘、不返回路径。
- **工具少而清晰**：只暴露 5 个工具，避免模型在工具选择上消耗上下文。
- **密钥不进入结果**：API Key、密码、临时下载地址不会返回给模型或写入日志。

## MCP 工具

| 工具 | 用途 |
|---|---|
| `search_torrents` | 搜索 PT 种子 |
| `download_torrents` | 把 PT 种子添加到 qBittorrent，可指定分类 |
| `list_download_categories` | 列出 qBittorrent 已有分类 |
| `list_downloads` | 查看下载/做种进度 |
| `get_config_status` | 检查配置与连接 |

### `search_torrents`

```python
search_torrents(
    keyword: str,
    page: int = 1,
    page_size: int = 20,
    categories: list[str] | None = None,
    sort_by: str = "seeders",
) -> dict
```

- `categories` 支持中文名（电影、剧集、动画、纪录片、音乐、游戏等）或分类 ID。
- `sort_by` 支持 `time`、`seeders`、`leechers`、`size`、`completed`。
- 只返回选择种子需要的字段：`index`、`id`、名称、大小、做种、下载、完成、优惠、分类、标签、发布时间。
- `index` 对应结果顺序，方便用户说“下载第 1 个和第 3 个”时映射到 `id`。

### `download_torrents`

```python
download_torrents(torrent_ids: list[str], category: str | None = None) -> dict
```

- `torrent_ids` 来自 `search_torrents` 的 `id`。
- 可先用 `list_download_categories` 查询分类，再用 `category` 指定已有分类；省略时使用 `QBITTORRENT_CATEGORY` 配置。
- 服务端从 M-Team 获取 `.torrent`，校验后直接上传 qBittorrent。
- 返回每个 ID 的 `ok`、`hash`、`name`、`message`。
- 支持批量，单个失败不会中断其他任务。

### `list_download_categories`

返回 qBittorrent 已有分类名称。用户要把种子放入指定分类时，先查询此工具并将选中的名称传给 `download_torrents`。

### `list_downloads`

```python
list_downloads(
    status: str = "all",
    hash: str | None = None,
    limit: int = 20,
) -> dict
```

- 不传 `hash` 时返回任务列表和汇总。
- 传 `hash` 时查看单个任务。
- `status` 支持 `all`、`downloading`、`seeding`、`completed`、`stopped`、`error` 及中文别名。
- 默认优先展示下载中的任务，不返回保存路径。

### `get_config_status`

```python
get_config_status(check_connectivity: bool = False) -> dict
```

- 默认只检查配置是否完整，不发起网络请求。
- `check_connectivity=true` 时验证 M-Team API Key、qBittorrent 认证、版本和分类。
- 不返回密钥、密码。

## 快速开始

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```bash
uv sync
cp .env.example .env
# 编辑 .env，填入 M-Team API Key 和 qBittorrent 配置
uv run nas-mcp --check
```

如果依赖下载缓慢，可以临时指定镜像：

```bash
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv sync
```

`--check` 会检查配置并尝试连接 M-Team 和 qBittorrent。

### 在 opencode 中使用

在 `opencode.json` / `opencode.jsonc` 中加入：

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
        "nas-mcp"
      ],
      "enabled": true
    }
  }
}
```

配置优先从项目目录下的 `.env` 自动加载。如果不使用 `.env`，可以在 `environment` 中直接传环境变量。

### 在 Claude Desktop 中使用

```json
{
  "mcpServers": {
    "nas-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/nas-mcp",
        "nas-mcp"
      ],
      "env": {
        "MTEAM_API_KEY": "你的 M-Team API Key",
        "QBITTORRENT_URL": "http://127.0.0.1:8080",
        "QBITTORRENT_BASIC_AUTH": "用户名:密码"
      }
    }
  }
}
```

### HTTP 模式

默认 stdio。需要远程访问时：

```bash
MCP_TRANSPORT=streamable-http uv run nas-mcp
# 或
uv run nas-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

客户端连接 `http://<host>:8000/mcp`。远程暴露时请自行加认证和网络隔离。

## 配置

复制 `.env.example` 为 `.env`。

### M-Team

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `MTEAM_API_KEY` | 是 | 无 | M-Team 存取令牌 |
| `MTEAM_API_BASE` | 否 | `https://api.m-team.cc/api` | API 根地址 |
| `MTEAM_SITE_URL` | 否 | `https://kp.m-team.cc` | 站点域名，API 要求 Origin 一致 |
| `MTEAM_TIMEOUT` | 否 | `30` | HTTP 超时秒数 |
| `MTEAM_MAX_TORRENT_MB` | 否 | `32` | 单个种子最大大小 |

API Key 获取位置：M-Team 控制台 → 实验室/API。

### qBittorrent

可使用 `QBITTORRENT_BASIC_AUTH` 对 WebUI 或其前置反向代理进行 HTTP Basic Auth；若 qBittorrent WebUI 使用内置登录，则设置用户名和密码。

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `QBITTORRENT_URL` | 是 | 无 | WebUI 地址，可省略 `http://` |
| `QBITTORRENT_BASIC_AUTH` | 否 | 无 | HTTP Basic Auth 凭据，格式为 `username:password`；设置后优先使用 |
| `QBITTORRENT_USERNAME` | 否 | 无 | 未设置 Basic Auth 时用于 qBittorrent WebUI 登录 |
| `QBITTORRENT_PASSWORD` | 否 | 无 | 未设置 Basic Auth 时用于 qBittorrent WebUI 登录 |
| `QBITTORRENT_SAVE_PATH` | 否 | 无 | 固定保存路径，设置后关闭 autoTMM |
| `QBITTORRENT_CATEGORY` | 否 | 无 | 分类名，不存在时自动创建 |
| `QBITTORRENT_TAGS` | 否 | 无 | 逗号分隔标签 |
| `QBITTORRENT_TIMEOUT` | 否 | `30` | HTTP 超时秒数 |

认证优先级：

1. 填写 `QBITTORRENT_BASIC_AUTH`：使用 `Authorization: Basic <credentials>`，不调用登录接口。
2. 未填写 Basic Auth，但设置了 `QBITTORRENT_USERNAME` 或 `QBITTORRENT_PASSWORD`：调用 qBittorrent 登录接口并使用会话 Cookie。
3. 两种方式都未设置：假设 qBittorrent 已关闭本地认证。

### 默认项

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PT_DEFAULT_SITE` | `mteam` | 默认 PT 站 |
| `DOWNLOADER_DEFAULT` | `qbittorrent` | 默认下载器 |
| `MCP_TRANSPORT` | `stdio` | `stdio` 或 `streamable-http` |
| `MCP_HOST` | `127.0.0.1` | HTTP 监听地址 |
| `MCP_PORT` | `8000` | HTTP 监听端口 |

## 工作流示例

用户：

> 帮我搜一下沙丘，做种多的。

AI：

```text
search_torrents(keyword="沙丘", sort_by="seeders")
```

用户：

> 下载第 1 个和第 3 个，放到 Movies 分类。

AI 先读取 qBittorrent 分类：

```text
list_download_categories()
```

确认结果中有 `Movies` 后再添加：

```text
download_torrents(torrent_ids=["1125330", "1125342"], category="Movies")
```

用户：

> 现在下载进度怎么样？

AI：

```text
list_downloads(status="downloading")
```

## 安全说明

- `.env` 已加入 `.gitignore`，不要提交真实密钥。
- M-Team 临时下载地址包含令牌，不返回给模型，也不记录日志。
- 下载种子时不会携带 `x-api-key`，避免跨域重定向泄露。
- qBittorrent 只添加任务，不提供删除、暂停等破坏性工具。
- 不提供“下载种子文件到本地”的工具，避免把 NAS 文件系统暴露给模型。

## 扩展新站点/下载器

### 新 PT 站

1. 在 `src/nas_mcp/providers/` 新建模块，继承 `PTProvider`。
2. 实现 `search`、`download`、`validate_torrent_id`、`categories`、`check_connectivity`、`status_info`。
3. 在 `providers/__init__.py` 的 `build_providers` 注册。
4. 在 `config.py` 增加对应配置。

### 新下载器

1. 在 `src/nas_mcp/downloaders/` 新建模块，继承 `Downloader`。
2. 实现 `add_torrent`、`list_categories`、`list_torrents`、`check_connectivity`、`status_info`。
3. 在 `downloaders/__init__.py` 的 `build_downloaders` 注册。
4. 在 `config.py` 增加对应配置。

MCP 工具层不需要改动。

## 开发

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run nas-mcp --check
```

测试使用 `httpx2.MockTransport`，不需要真实 M-Team 或 qBittorrent。
