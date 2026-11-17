# syntax=docker/dockerfile:1

# ---- 构建阶段：用 uv 安装依赖和项目 ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 先只复制依赖清单，依赖不变时复用这一层缓存
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- 运行阶段：只带虚拟环境和源码产物，不含构建工具 ----
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app

RUN useradd --system --uid 10001 --create-home app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, socket; socket.create_connection(('127.0.0.1', int(os.getenv('MCP_PORT', '8000'))), 3).close()"]

# 默认读取 MCP_TRANSPORT 等环境变量，可在命令后追加参数覆盖，例如 --transport stdio
ENTRYPOINT ["nas-mcp"]
