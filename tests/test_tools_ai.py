"""ai 模块工具测试（端到端，用 respx mock）。

ai 模块尚未注册到 src/mcp_1panel/server.py（主 agent 统一加），所以这里
单独构造一个 FastMCP 实例并注册 ai.register，独立测试 ai 工具集。
不打真实 1Panel，全部走 respx mock。

测试要点：
1. 工具注册（33 个工具名齐全）
2. 读工具端到端（ai_model_list / ai_gpu_status / ai_agent_list）
3. 写工具安全校验（require_write 只读模式 / confirm 高危）
4. 写工具正常路径端到端（ai_model_pull / ai_model_delete）
"""

from __future__ import annotations

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_1panel.config import get_settings
from mcp_1panel.tools import ai
from .helpers import parse_tool_result


# ---- 构造独立 mcp 实例（避免依赖 server.py 注册）----

@pytest.fixture
def mcp():
    """注册了 ai 模块的独立 FastMCP 实例。"""
    server = FastMCP("1Panel-test-ai")
    ai.register(server)
    return server


# 33 个工具名（与 ai.py 中定义的 @mcp.tool 一一对应）
EXPECTED_TOOLS = {
    # Ollama 模型管理 (7)
    "ai_model_list", "ai_model_search", "ai_model_pull", "ai_model_recreate",
    "ai_model_delete", "ai_model_sync", "ai_model_close",
    # GPU (1)
    "ai_gpu_status",
    # 域名 (2)
    "ai_domain_get", "ai_domain_bind",
    # Agent 主管理 (6)
    "ai_agent_list", "ai_agent_providers", "ai_agent_create", "ai_agent_delete",
    "ai_agent_model_update", "ai_agent_token_reset",
    # Agent 账户 (5)
    "ai_account_list", "ai_account_create", "ai_account_update",
    "ai_account_delete", "ai_account_verify",
    # Agent 浏览器/其它 (4)
    "ai_agent_browser_get", "ai_agent_browser_update",
    "ai_agent_other_get", "ai_agent_other_update",
    # Agent 渠道 (8)
    "ai_agent_discord_get", "ai_agent_discord_update",
    "ai_agent_telegram_get", "ai_agent_telegram_update",
    "ai_agent_feishu_get", "ai_agent_feishu_update",
    "ai_agent_feishu_pairing_approve", "ai_agent_channel_pairing_approve",
}


# ---- 注册验证 ----

async def test_ai_tools_registered(mcp):
    """ai 模块的 33 个工具应全部注册。"""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"缺少工具: {missing}"
    # 数量精确匹配（防止漏列）
    extra = names - EXPECTED_TOOLS
    assert not extra, f"多余工具: {extra}"


async def test_ai_tools_count(mcp):
    """工具总数应正好是 33。"""
    tools = await mcp.list_tools()
    assert len(tools) == 33


# ---- 读工具端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_ai_model_list_e2e(mcp):
    """ai_model_list 应调 POST /ai/ollama/model/load 并返回分页数据。"""
    respx.post("http://1panel.test/api/v2/ai/ollama/model/load").respond(
        json={"code": 200, "message": "", "data": {"items": [{"name": "llama3.2"}], "total": 1}}
    )
    result = await mcp.call_tool("ai_model_list", {"page": 1})
    data = parse_tool_result(result)
    assert data["total"] == 1
    assert data["items"][0]["name"] == "llama3.2"
    # 校验请求体含分页参数
    request = respx.calls.last.request
    assert '"info"' in request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_ai_gpu_status_e2e(mcp):
    """ai_gpu_status 应调 GET /ai/gpu/load。"""
    respx.get("http://1panel.test/api/v2/ai/gpu/load").respond(
        json={"code": 200, "message": "", "data": {"gpus": [{"name": "RTX 4090", "memoryUsed": "2GB"}]}}
    )
    result = await mcp.call_tool("ai_gpu_status", {})
    data = parse_tool_result(result)
    assert data["gpus"][0]["name"] == "RTX 4090"


@pytest.mark.asyncio
@respx.mock
async def test_ai_agent_list_e2e(mcp):
    """ai_agent_list 应调 POST /ai/agents/search。"""
    respx.post("http://1panel.test/api/v2/ai/agents/search").respond(
        json={"code": 200, "message": "", "data": {"items": [{"id": 1, "name": "my-agent"}], "total": 1}}
    )
    result = await mcp.call_tool("ai_agent_list", {"info": "my"})
    data = parse_tool_result(result)
    assert data["items"][0]["name"] == "my-agent"
    # 校验 info 过滤被透传
    body = respx.calls.last.request.content.decode()
    assert '"my"' in body


@pytest.mark.asyncio
@respx.mock
async def test_ai_account_verify_e2e(mcp):
    """ai_account_verify 是读探测，应直接放行调 POST /ai/agents/accounts/verify。"""
    respx.post("http://1panel.test/api/v2/ai/agents/accounts/verify").respond(
        json={"code": 200, "message": "", "data": {"valid": True}}
    )
    result = await mcp.call_tool("ai_account_verify", {
        "provider": "openai", "api_key": "sk-test",
    })
    data = parse_tool_result(result)
    assert data["valid"] is True


# ---- 写工具：只读模式拦截 ----

@pytest.mark.asyncio
async def test_ai_model_pull_rejected_in_readonly(mcp, monkeypatch):
    """只读模式下写操作应被拒绝，且不发起请求。"""
    monkeypatch.setenv("PANEL_READONLY", "true")
    get_settings.cache_clear()
    assert get_settings().panel_readonly is True

    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/ai/ollama/model")
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("ai_model_pull", {"name": "llama3.2"})
        assert "只读模式" in str(exc_info.value)
        assert not route.called

    monkeypatch.setenv("PANEL_READONLY", "false")
    get_settings.cache_clear()


# ---- 写工具：高危 confirm 拦截 ----

@pytest.mark.asyncio
async def test_ai_model_delete_requires_confirm(mcp):
    """ai_model_delete 不传 confirm=true 应拒绝（不发起请求）。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/ai/ollama/model/del")
        with pytest.raises(Exception):
            await mcp.call_tool("ai_model_delete", {"model_ids": [1]})
        assert not route.called


@pytest.mark.asyncio
async def test_ai_agent_delete_requires_confirm(mcp):
    """ai_agent_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/ai/agents/delete")
        with pytest.raises(Exception):
            await mcp.call_tool("ai_agent_delete", {"agent_id": 1})
        assert not route.called


@pytest.mark.asyncio
async def test_ai_account_delete_requires_confirm(mcp):
    """ai_account_delete 不传 confirm=true 应拒绝。"""
    with respx.mock:
        route = respx.post("http://1panel.test/api/v2/ai/agents/accounts/delete")
        with pytest.raises(Exception):
            await mcp.call_tool("ai_account_delete", {"account_id": 1})
        assert not route.called


# ---- 写工具正常路径端到端 ----

@pytest.mark.asyncio
@respx.mock
async def test_ai_model_pull_e2e(mcp):
    """ai_model_pull 传 name 应调 POST /ai/ollama/model。"""
    respx.post("http://1panel.test/api/v2/ai/ollama/model").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("ai_model_pull", {"name": "qwen2.5:7b"})
    body = respx.calls.last.request.content.decode()
    assert '"qwen2.5:7b"' in body


@pytest.mark.asyncio
@respx.mock
async def test_ai_model_delete_with_confirm_e2e(mcp):
    """ai_model_delete 传 confirm=true 应真正调 API 并传 forceDelete。"""
    respx.post("http://1panel.test/api/v2/ai/ollama/model/del").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("ai_model_delete", {
        "model_ids": [1, 2], "force": True, "confirm": True,
    })
    body = respx.calls.last.request.content.decode()
    assert '"ids"' in body
    assert '"forceDelete"' in body


@pytest.mark.asyncio
@respx.mock
async def test_ai_domain_bind_e2e(mcp):
    """ai_domain_bind 应调 POST /ai/domain/bind，可选字段缺省时不入 body。"""
    respx.post("http://1panel.test/api/v2/ai/domain/bind").respond(
        json={"code": 200, "message": "", "data": None}
    )
    await mcp.call_tool("ai_domain_bind", {
        "app_install_id": 5, "domain": "ollama.example.com",
    })
    import json as _json
    sent = _json.loads(respx.calls.last.request.content)
    assert sent["appInstallID"] == 5
    assert sent["domain"] == "ollama.example.com"
    # 必填字段兜底：ipList 始终带（空串）
    assert sent["ipList"] == ""
    # sslID/websiteID 未传不应出现在 body
    assert "sslID" not in sent
    assert "websiteID" not in sent
