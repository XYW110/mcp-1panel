.PHONY: help install dev test test-cov run run-http run-stdio inspector up down build clean

help:  ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## 用 venv + pip 安装项目（开发模式）
	python -m venv .venv
	.venv/Scripts/python -m pip install --upgrade pip
	.venv/Scripts/pip install -e ".[dev]"

dev:  ## 用 uv 安装（需先装 uv）
	uv sync --extra dev

test:  ## 运行全部测试
	.venv/Scripts/python -m pytest tests/ -v

test-cov:  ## 运行测试并生成覆盖率报告
	.venv/Scripts/python -m pytest tests/ --cov=src/mcp_1panel --cov-report=term-missing

run:  ## 启动 MCP server（streamable-http，默认）
	.venv/Scripts/python -m mcp_1panel

run-http:  ## 以 streamable-http 模式启动（生产/容器）
	.venv/Scripts/python -m mcp_1panel --transport http --host 0.0.0.0 --port 8000

run-stdio:  ## 以 stdio 模式启动（本地调试，Cursor 直连）
	.venv/Scripts/python -m mcp_1panel --transport stdio

up:  ## docker compose 启动全部服务（mcphub + onepanel-mcp + postgres）
	docker compose up -d --build

down:  ## 停止并清理 compose 服务
	docker compose down

build:  ## 构建镜像
	docker build -t mcp-1panel .

clean:  ## 清理缓存
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
