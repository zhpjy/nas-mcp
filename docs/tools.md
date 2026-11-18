# 工具与工作流

nas-mcp 只暴露 5 个 MCP 工具，避免模型在工具选择上消耗上下文。

| 工具 | 用途 |
|---|---|
| `search_torrents` | 搜索 PT 种子 |
| `download_torrents` | 把 PT 种子添加到 qBittorrent，可指定分类 |
| `list_download_categories` | 列出 qBittorrent 已有分类 |
| `list_downloads` | 查看下载/做种进度 |
| `get_config_status` | 检查配置与连接 |

成人内容开关是服务端配置，不出现在工具参数或工具结果中。

## `search_torrents`

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
- 未启用成人内容时，成人分类会从请求中移除；如果移除后没有剩余分类，则搜索普通分类。
  返回结果中的成人条目也会被丢弃。
- `sort_by` 支持 `time`、`seeders`、`leechers`、`size`、`completed`。
- 只返回选择种子需要的字段：`index`、`id`、名称、大小、做种、下载、完成、优惠、分类、标签、发布时间。
- `index` 对应结果顺序，方便用户说“下载第 1 个和第 3 个”时映射到 `id`。

## `download_torrents`

```python
download_torrents(torrent_ids: list[str], category: str | None = None) -> dict
```

- `torrent_ids` 来自 `search_torrents` 的 `id`。
- 可先用 `list_download_categories` 查询分类，再用 `category` 指定已有分类；
  省略时使用 `qbittorrent.category` 配置。
- 服务端从 M-Team 获取 `.torrent`，校验后直接上传 qBittorrent。
- 返回每个 ID 的 `ok`、`hash`、`name`、`message`。
- 支持批量，单个失败不会中断其他任务。
- 下载链接过期、429/5xx 或网络中断时，服务端会自动重新申请链接并重试，最多 5 次；
  退避从 0.5 秒开始指数增长，单次最长 3 秒；仍失败才把错误返回给调用方。

## `list_download_categories`

返回 qBittorrent 已有分类名称。用户要把种子放入指定分类时，先查询此工具并将选中的名称传给
`download_torrents`。

## `list_downloads`

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

## `get_config_status`

```python
get_config_status(check_connectivity: bool = False) -> dict
```

- 默认只检查配置是否完整，不发起网络请求。
- `check_connectivity=true` 时验证 M-Team API Key、qBittorrent 认证、版本和分类。
- 不返回密钥、密码、access key 或成人内容开关。

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
