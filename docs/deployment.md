# Docker 部署与镜像发布

镜像默认使用 `streamable-http`，在容器内监听 `0.0.0.0:8000`，MCP 端点为 `/mcp`。
运行时通过只读挂载的 `config.yaml` 配置，配置文件不会打进镜像。
服务不保存种子文件，不需要挂载下载目录或数据卷。

配置字段见 [配置](configuration.md)。

## 本地构建

复制 `config.example.yaml` 为 `config.yaml` 并填写配置，然后运行：

```bash
docker compose up -d --build
docker compose logs -f nas-mcp
```

`compose.yaml` 把 `config.yaml` 以只读方式挂载到容器内的 `/app/config.yaml`。
镜像内以 uid `10001` 的 `app` 用户运行，因此挂载的文件需要对该用户可读；
在多数 NAS 上可以执行 `chmod 644 config.yaml`，或者用 `user:` 指定一个能读取该文件的用户。
只在本机使用 stdio 时，`chmod 600 config.yaml` 即可。

仓库中的 Compose 默认只发布到宿主机 `127.0.0.1:8000`。需要可信局域网内的客户端直接访问时，
将 `ports` 改成 `"8000:8000"`，连接 `http://<NAS-IP>:8000/mcp`。
未配置 `access_keys` 时服务不做客户端认证；公网访问仍需在前面配置 HTTPS 和认证代理。

容器内的 `127.0.0.1` 指容器自身。qBittorrent 在宿主机上时，将 `config.yaml` 中的
`qbittorrent.url` 改为 `http://host.docker.internal:8080`（Compose 已配置宿主机映射），
或使用 NAS 的局域网地址。qBittorrent 必须监听该地址可访问的接口。
`qbittorrent.save_path` 是 qBittorrent 所见的路径，不是 MCP 容器内的路径。

镜像的健康检查只检测 8000 端口。需要验证真实配置和上游连接时，可运行：

```bash
docker compose exec nas-mcp nas-mcp --check
```

## 发布到 GHCR

仓库包含 `.github/workflows/docker.yml`，使用 GitHub Actions 自带的 `GITHUB_TOKEN` 发布，
无需另配仓库密码。镜像名为 `ghcr.io/<owner>/nas-mcp`，支持 `linux/amd64` 和 `linux/arm64`。

- 推送 `main`：发布 `main`、`latest` 和对应提交的 `sha-...` 标签。
- 推送版本标签，例如 `v0.2.2`：发布 `0.2.2`、`0.2` 和对应提交标签。
- Pull request：仅构建，不推送镜像。

版本标签还会触发 `.github/workflows/release.yml`，运行测试并把 sdist、wheel 上传到
GitHub Release，可直接配合 `uvx` 使用，见 [README](../README.md#用-uvx-运行)。

`latest` 跟随主分支，NAS 长期部署建议固定版本标签。首次发布后，在 GitHub Package 设置中
将镜像设为 Public 即可匿名拉取；保留 Private 时，NAS 需要先登录 GHCR 并具有拉取权限。
版本标签应与 `pyproject.toml` 中的版本对应。

## NAS 使用已发布的镜像

发布成功后，NAS 只需要 `config.yaml` 和下面的 `compose.yaml`，无需 Python、uv 或源码。
将 `<owner>` 替换为实际 GitHub 用户或组织名（镜像路径使用小写），版本替换为已发布版本：

```yaml
services:
  nas-mcp:
    image: ghcr.io/<owner>/nas-mcp:0.2.2
    restart: unless-stopped
    init: true
    command: ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
    volumes:
      # 容器内以 uid 10001 运行；确保该用户能读取 config.yaml
      - ./config.yaml:/app/config.yaml:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "8000:8000"
```

此示例用于可信局域网直连；配置了 `access_keys` 后，客户端还需要携带对应 Bearer key。
部署或更换镜像版本后运行 `docker compose pull` 和 `docker compose up -d`；
客户端始终连接 `http://<NAS-IP>:8000/mcp`。
