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
        choices=["http", "stdio", "sse"],
        default=os.getenv("MCP_TRANSPORT", "http"),
        help="传输方式，默认 http（streamable-http），与 mcphub 对接",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="HTTP/SSE 监听地址，容器内必须 0.0.0.0",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="HTTP/SSE 监听端口",
    )
    args = parser.parse_args()

    s = get_settings()
    try:
        s.assert_panel_configured()
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(2)

    log.info(
        "启动 1Panel MCP server: transport=%s endpoint=%s readonly=%s",
        args.transport,
        s.panel_endpoint,
        s.panel_readonly,
    )

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # streamable-http 用 "http"；sse 向后兼容
        mcp.run(transport="sse" if args.transport == "sse" else "http",
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
