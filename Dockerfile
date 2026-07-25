# 多阶段构建：构建阶段用 uv 装依赖，运行阶段用 slim 镜像
# 最终镜像仅含 Python + 依赖，无构建工具，体积小

# ---- 构建阶段：装依赖到 .venv ----
FROM python:3.12-slim AS builder

# 装 uv（快速 Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 先拷依赖清单和 README（pyproject.toml 引用了 readme = "README.md"）
COPY pyproject.toml README.md ./
COPY src ./src

# 用 uv 创建虚拟环境并装依赖（--frozen 保证可复现）
RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python -e ".[]"

# ---- 运行阶段：仅复制 .venv 和源码 ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# 从构建阶段复制虚拟环境
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY pyproject.toml ./

# 把 venv 加进 PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

# 健康检查（streamable-http 端点需 POST initialize，GET 会 405）
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python -c "import urllib.request,json;req=urllib.request.Request('http://127.0.0.1:8000/mcp',data=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'hc','version':'1'}}}).encode(),headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'});urllib.request.urlopen(req,timeout=5)" || exit 1

EXPOSE 8000

# 直接运行 entry point（transport=streamable-http；host/port 由环境变量控制）
CMD ["mcp-1panel", "--transport", "streamable-http"]
