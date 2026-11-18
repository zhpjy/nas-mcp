# 开发

## 设计原则

- **不向 AI 暴露文件**：种子只在服务端内存中流转，直接上传 qBittorrent，不落盘、不返回路径。
- **工具少而清晰**：只暴露 5 个工具，避免模型在工具选择上消耗上下文。
- **密钥不进入结果**：API Key、access key、密码、临时下载地址不会返回给模型或写入日志。
- **成人内容默认关闭**：开关只存在于服务端配置，不暴露为工具参数或状态字段；
  关闭时不会返回成人板块条目。

## 环境与验证

要求 Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run nas-mcp --check
```

依赖下载缓慢时可以临时指定镜像：

```bash
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv sync
```

测试使用 `httpx2.MockTransport`，不需要真实 M-Team 或 qBittorrent。

## 扩展新 PT 站

1. 在 `src/nas_mcp/providers/` 新建模块，继承 `PTProvider`。
2. 实现 `search`、`download`、`validate_torrent_id`、`categories`、`check_connectivity`、
   `status_info`；`search` 必须遵守 `include_adult`，关闭时过滤成人分类和成人结果。
3. 在 `providers/__init__.py` 的 `build_providers` 注册。
4. 在 `config.py` 增加对应配置。

## 扩展新下载器

1. 在 `src/nas_mcp/downloaders/` 新建模块，继承 `Downloader`。
2. 实现 `add_torrent`、`list_categories`、`list_torrents`、`check_connectivity`、`status_info`。
3. 在 `downloaders/__init__.py` 的 `build_downloaders` 注册。
4. 在 `config.py` 增加对应配置。

MCP 工具层不需要改动。
