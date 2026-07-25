"""CLI 入口：启动 MCP server。

支持三种传输方式（默认 streamable-http，mcphub compose 场景）：
    mcp-1panel                              # 等同 --transport http
    mcp-1panel --transport http             # streamable-http，容器内监听 0.0.0.0:8000
    mcp-1panel --transport stdio            # 本地调试，Cursor 直连
    python -m mcp_1panel --transport http --host 0.0.0.0 --port 8000

环境变量（见 config.py）：
    MCP_TRANSPORT / MCP_HOST / MCP_PORT
    PANEL_ENDPOINT / PANEL_API_KEY / PANEL_TIMEOUT / PANEL_READONLY
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import get_settings
from .server import mcp


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main() -> None:
    _setup_logging()
    log = logging.getLogger("mcp-1panel")

    parser = argparse.ArgumentParser(
        prog="mcp-1panel",
        description="1Panel 全功能 MCP server（Python 手写，对接 v2 API）",
    )
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "stdio", "sse"],
        default=os.getenv("MCP_TRANSPORT", "streamable-http"),
        help="传输方式，默认 streamable-http，与 mcphub 对接",
    )
    # host/port 通过环境变量 MCP_HOST/MCP_PORT 在 server.py 初始化时传给 FastMCP
    # 这里保留 --host/--port 参数仅为兼容，实际生效需重启（run() 不接受这些参数）
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"), help="HTTP 监听地址（通过环境变量 MCP_HOST 生效）")
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")), help="HTTP 监听端口（通过环境变量 MCP_PORT 生效）")
    args = parser.parse_args()

    s = get_settings()
    try:
        s.assert_panel_configured()
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(2)

    log.info(
        "启动 1Panel MCP server: transport=%s host=%s port=%s endpoint=%s readonly=%s",
        args.transport, args.host, args.port, s.panel_endpoint, s.panel_readonly,
    )

    # FastMCP.run() 只接受 transport 参数；host/port 在 FastMCP 初始化时已从环境变量读取
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
