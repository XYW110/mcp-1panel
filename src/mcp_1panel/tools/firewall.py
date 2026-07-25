"""防火墙模块（对应 openapi.json 的 Firewall tag，15 个端点）。

实现风格沿用 container.py 黄金范式：
1. 工具名 firewall_<object>_<action>（base / rules_search / port_operate /
   ip_operate / forward_operate / filter_* / operate / batch / update_*）
2. description 用 `[防火墙] xxx。读操作。` / `⚠️写操作 [防火墙] xxx。` /
   `⚠️高危 [防火墙] xxx。` 结构化前缀，便于 mcphub 向量搜索召回
3. 入参用 Annotated[T, Field(description=...)] + Literal 枚举，复杂嵌套（批量规则
   数组、update 的 old/new 对）通过 list[dict] / dict 直传
4. handler 用 `await get_client()` 拿共享客户端，调 .post()（firewall 全部 POST）
5. 安全分层：写操作开头 require_write()；rule_remove / firewall stop 等
   高危操作额外加 confirm 参数
6. 防火墙错误配置可能导致 SSH 断连，所有写操作均需 confirm 二次确认

接口来源：references/openapi.json 的 /hosts/firewall/* 路径，basePath /api/v2。
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..client import get_client
from ..safety import require_write


# ---- 枚举（来自 openapi.json definitions）----

# 防火墙规则分类（RuleSearch/BatchRuleOperate.type，1Panel 源码 FirewallRuleType）
RuleType = Literal["port", "addr", "forward"]

# 端口/地址规则策略
PortStrategy = Literal["accept", "drop"]
# iptables filter 链策略多了 reject
FilterStrategy = Literal["accept", "drop", "reject"]
PortProtocol = Literal["tcp", "udp", "tcp/udp"]
RuleOperation = Literal["add", "remove"]

# 防火墙启停
FirewallOp = Literal["start", "stop", "restart", "disableBanPing", "enableBanPing"]
# iptables filter 链名（规则级别）
FilterChain = Literal["1PANEL_BASIC", "1PANEL_BASIC_BEFORE", "1PANEL_INPUT", "1PANEL_OUTPUT"]
# iptables filter 链名（链操作级别）
FilterChainName = Literal["1PANEL_INPUT", "1PANEL_OUTPUT", "1PANEL_BASIC"]
# iptables filter 操作（apply/unload/init 系列）
FilterOperate = Literal[
    "init-base", "init-forward", "init-advance",
    "bind-base", "unbind-base", "bind", "unbind",
]


def register(mcp: FastMCP) -> None:

    # ---- 基础信息 / 状态（读） ----

    @mcp.tool()
    async def firewall_base(
        name: Annotated[str, Field(description="主机名称（1Panel 中注册的 host name），用于定位目标主机防火墙")] = "",
    ) -> dict:
        """[防火墙] 获取防火墙基础信息（是否激活、版本、ping 状态）。读操作。

        返回 FirewallBaseInfo：name / version / isActive / isBind / isExist /
        isInit / pingStatus。对应 POST /hosts/firewall/base。

        Args:
            name: 目标主机名，留空表示当前主机。对应后端 OperationWithName.name。
        """
        client = await get_client()
        return await client.post("/hosts/firewall/base", {"name": name})

    @mcp.tool()
    async def firewall_filter_chain_status(
        name: Annotated[str, Field(description="主机名，留空表示当前主机")] = "",
    ) -> dict:
        """[防火墙] 查询 iptables filter 链状态。读操作。

        返回 1PANEL_INPUT/OUTPUT 等链的绑定/初始化状态。对应 POST
        /hosts/firewall/filter/chain/status。

        Args:
            name: 目标主机名。
        """
        client = await get_client()
        return await client.post("/hosts/firewall/filter/chain/status", {"name": name})

    @mcp.tool()
    async def firewall_rules_search(
        rule_type: Annotated[RuleType, Field(description="规则分类：port 端口规则 / addr IP规则 / forward 端口转发")] = "port",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        info: Annotated[Optional[str], Field(description="关键字模糊匹配（端口/IP/描述），留空不过滤")] = None,
        status: Annotated[Optional[str], Field(description="状态过滤，如 enabled/disabled，留空不过滤")] = None,
        strategy: Annotated[Optional[PortStrategy], Field(description="策略过滤：accept/drop，留空不过滤")] = None,
    ) -> dict:
        """[防火墙] 分页查询防火墙规则列表（端口 / IP / 转发统一入口）。读操作。

        对应 POST /hosts/firewall/search，body 用 RuleSearch。type 决定返回哪类规则：
        port → 端口放行/拒绝规则、addr → IP 规则、forward → 端口转发规则。

        Args:
            rule_type: 规则分类，默认 port。
            page: 页码，从 1 开始。
            page_size: 每页数量，上限 500。
            info: 关键字过滤。
            status: 状态过滤。
            strategy: 策略过滤。
        """
        client = await get_client()
        body: dict = {
            "type": rule_type,
            "page": page,
            "pageSize": page_size,
        }
        if info is not None:
            body["info"] = info
        if status is not None:
            body["status"] = status
        if strategy is not None:
            body["strategy"] = strategy
        return await client.post("/hosts/firewall/search", body)

    @mcp.tool()
    async def firewall_filter_search(
        filter_type: Annotated[str, Field(description="filter 规则类型，按链区分，常用值见 1Panel 链名")] = "",
        page: Annotated[int, Field(ge=1, description="页码")] = 1,
        page_size: Annotated[int, Field(ge=1, le=500, description="每页数量")] = 100,
        info: Annotated[Optional[str], Field(description="关键字模糊匹配，留空不过滤")] = None,
    ) -> dict:
        """[防火墙] 分页查询 iptables filter 高级规则。读操作。

        返回 1PANEL_BASIC / 1PANEL_INPUT / 1PANEL_OUTPUT 链上的自定义 iptables 规则。
        对应 POST /hosts/firewall/filter/search，body 用 SearchPageWithType。

        Args:
            filter_type: filter 规则类型（链标识），用于区分查询范围。
            page: 页码。
            page_size: 每页数量。
            info: 关键字过滤。
        """
        client = await get_client()
        body: dict = {
            "type": filter_type,
            "page": page,
            "pageSize": page_size,
        }
        if info is not None:
            body["info"] = info
        return await client.post("/hosts/firewall/filter/search", body)

    # ---- 端口规则（写） ----

    @mcp.tool()
    async def firewall_port_operate(
        operation: Annotated[RuleOperation, Field(description="操作：add 新建 / remove 删除")],
        port: Annotated[str, Field(description="端口号或范围，如 8080、8000-8100")],
        protocol: Annotated[PortProtocol, Field(description="协议：tcp / udp / tcp/udp")],
        strategy: Annotated[PortStrategy, Field(description="策略：accept 放行 / drop 拒绝")],
        address: Annotated[Optional[str], Field(description="限定来源 IP/CIDR，留空表示所有来源")] = None,
        description: Annotated[Optional[str], Field(description="规则备注")] = None,
        id: Annotated[Optional[int], Field(description="规则 ID，remove 时必填")] = None,
        chain: Annotated[Optional[str], Field(description="链名，一般留空由后端决定")] = None,
        confirm: Annotated[bool, Field(description="防火墙写操作风险高，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 新增/删除端口规则。

        错误配置可能导致 SSH 断连，必须显式传 confirm=true。对应 POST
        /hosts/firewall/port，body 用 PortRuleOperate。

        Args:
            operation: add 新建规则 / remove 删除规则。
            port: 端口号或范围，如 22、8080、8000-8100。
            protocol: 协议。
            strategy: accept 放行 / drop 拒绝。
            address: 限定来源 IP/CIDR（如 192.168.1.0/24），留空表示 0.0.0.0/0。
            description: 规则备注。
            id: 规则 ID，删除时必填。
            chain: 链名，一般留空。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "防火墙端口规则操作可能影响 SSH 等关键访问，必须显式传 confirm=true。"
            )
        client = await get_client()
        body: dict = {
            "operation": operation,
            "port": port,
            "protocol": protocol,
            "strategy": strategy,
        }
        if address is not None:
            body["address"] = address
        if description is not None:
            body["description"] = description
        if id is not None:
            body["id"] = id
        if chain is not None:
            body["chain"] = chain
        return await client.post("/hosts/firewall/port", body)

    @mcp.tool()
    async def firewall_port_update(
        old_rule: Annotated[dict, Field(description="原端口规则，结构同 PortRuleOperate（operation/port/protocol/strategy 等）")],
        new_rule: Annotated[dict, Field(description="新端口规则，结构同 PortRuleOperate")],
        confirm: Annotated[bool, Field(description="防火墙写操作风险高，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 修改端口规则。

        对应 POST /hosts/firewall/update/port，body 用 PortRuleUpdate{oldRule,newRule}，
        两参数均为完整 PortRuleOperate 对象。

        Args:
            old_rule: 原规则（含 id/port/protocol/strategy/operation=remove 等）。
            new_rule: 新规则（operation=add）。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("防火墙规则修改风险高，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/firewall/update/port", {
            "oldRule": old_rule, "newRule": new_rule,
        })

    # ---- IP 规则（写） ----

    @mcp.tool()
    async def firewall_ip_operate(
        address: Annotated[str, Field(description="IP 或 CIDR，如 192.168.1.10 或 10.0.0.0/8")],
        operation: Annotated[RuleOperation, Field(description="操作：add 新建 / remove 删除")],
        strategy: Annotated[PortStrategy, Field(description="策略：accept 放行 / drop 拒绝")],
        description: Annotated[Optional[str], Field(description="规则备注")] = None,
        id: Annotated[Optional[int], Field(description="规则 ID，remove 时必填")] = None,
        confirm: Annotated[bool, Field(description="防火墙写操作风险高，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 新增/删除 IP 规则。

        错误配置可能封锁合法 IP，必须显式传 confirm=true。对应 POST
        /hosts/firewall/ip，body 用 AddrRuleOperate。

        Args:
            address: IP 或 CIDR。
            operation: add / remove。
            strategy: accept / drop。
            description: 规则备注。
            id: 规则 ID，删除时必填。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "防火墙 IP 规则操作可能影响访问，必须显式传 confirm=true。"
            )
        client = await get_client()
        body: dict = {
            "address": address,
            "operation": operation,
            "strategy": strategy,
        }
        if description is not None:
            body["description"] = description
        if id is not None:
            body["id"] = id
        return await client.post("/hosts/firewall/ip", body)

    @mcp.tool()
    async def firewall_ip_update(
        old_rule: Annotated[dict, Field(description="原 IP 规则，结构同 AddrRuleOperate（address/operation/strategy 等）")],
        new_rule: Annotated[dict, Field(description="新 IP 规则，结构同 AddrRuleOperate")],
        confirm: Annotated[bool, Field(description="防火墙写操作风险高，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 修改 IP 规则。

        对应 POST /hosts/firewall/update/addr，body 用 AddrRuleUpdate{oldRule,newRule}。

        Args:
            old_rule: 原 IP 规则。
            new_rule: 新 IP 规则。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("防火墙 IP 规则修改风险高，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/firewall/update/addr", {
            "oldRule": old_rule, "newRule": new_rule,
        })

    # ---- 端口转发（写） ----

    @mcp.tool()
    async def firewall_forward_operate(
        rules: Annotated[list[dict], Field(description="转发规则列表，每条含 operation/port/protocol/targetPort(必填)，可选 interface/targetIP/num")],
        force_delete: Annotated[bool, Field(description="是否强制删除（忽略校验），默认 false")] = False,
        confirm: Annotated[bool, Field(description="防火墙写操作风险高，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 批量新增/删除端口转发规则。

        对应 POST /hosts/firewall/forward，body 用 ForwardRuleOperate。每条 rule 必填
        operation/port/protocol/targetPort，可选 interface（网卡）/targetIP（目标 IP）/
        num（规则序号，删除时定位用）。

        Args:
            rules: 转发规则列表。例如
                [{"operation":"add","port":"8080","protocol":"tcp","targetPort":"80","targetIP":"192.168.1.5"}]。
            force_delete: 强制删除。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("防火墙端口转发操作风险高，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/firewall/forward", {
            "rules": rules, "forceDelete": force_delete,
        })

    # ---- 规则描述更新（写） ----

    @mcp.tool()
    async def firewall_rule_description_update(
        type: Annotated[str, Field(description="规则类型：port / addr / forward")],
        description: Annotated[str, Field(description="新描述")],
        strategy: Annotated[PortStrategy, Field(description="策略：accept / drop（定位规则用）")],
        chain: Annotated[Optional[str], Field(description="链名，一般留空")] = None,
        protocol: Annotated[Optional[str], Field(description="协议，定位端口规则用")] = None,
        src_ip: Annotated[Optional[str], Field(description="源 IP，定位 iptables 规则用")] = None,
        src_port: Annotated[Optional[str], Field(description="源端口")] = None,
        dst_ip: Annotated[Optional[str], Field(description="目的 IP")] = None,
        dst_port: Annotated[Optional[str], Field(description="目的端口")] = None,
        confirm: Annotated[bool, Field(description="写操作风险高，必须传 true")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 更新规则描述。

        对应 POST /hosts/firewall/update/description，body 用 UpdateFirewallDescription。
        通过 type+strategy+协议/IP/端口组合定位目标规则。

        Args:
            type: 规则类型。
            description: 新描述文本。
            strategy: 策略，定位规则用。
            chain: 链名。
            protocol: 协议。
            src_ip/src_port/dst_ip/dst_port: iptables 规则定位字段。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("防火墙规则更新风险高，必须显式传 confirm=true。")
        client = await get_client()
        body: dict = {"type": type, "description": description, "strategy": strategy}
        if chain is not None:
            body["chain"] = chain
        if protocol is not None:
            body["protocol"] = protocol
        if src_ip is not None:
            body["srcIP"] = src_ip
        if src_port is not None:
            body["srcPort"] = src_port
        if dst_ip is not None:
            body["dstIP"] = dst_ip
        if dst_port is not None:
            body["dstPort"] = dst_port
        return await client.post("/hosts/firewall/update/description", body)

    # ---- 批量操作（写） ----

    @mcp.tool()
    async def firewall_rule_batch(
        type: Annotated[str, Field(description="规则类型：port / addr / forward")],
        rules: Annotated[list[dict], Field(description="规则列表，每条结构同 PortRuleOperate（operation/port/protocol/strategy 等）")],
        confirm: Annotated[bool, Field(description="批量操作风险高，必须传 true")] = False,
    ) -> dict:
        """⚠️写操作 [防火墙] 批量操作端口/IP 规则。

        对应 POST /hosts/firewall/batch，body 用 BatchRuleOperate。type 决定规则类别，
        rules 为 PortRuleOperate 数组（含 operation=add/remove）。

        Args:
            type: 规则类型。
            rules: 规则列表，例如
                [{"operation":"add","port":"80","protocol":"tcp","strategy":"accept"}]。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError("防火墙批量操作风险高，必须显式传 confirm=true。")
        client = await get_client()
        return await client.post("/hosts/firewall/batch", {"type": type, "rules": rules})

    # ---- 防火墙启停（写，高危） ----

    @mcp.tool()
    async def firewall_operate(
        operation: Annotated[FirewallOp, Field(description="操作：start 启动 / stop 停止 / restart 重启 / disableBanPing / enableBanPing")],
        with_docker_restart: Annotated[bool, Field(description="是否同时重启 docker（避免容器网络受影响），默认 false")] = False,
        confirm: Annotated[bool, Field(description="高危操作，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [防火墙] 启停/重启防火墙（ufw）。

        停止或错误重启防火墙可能导致 SSH 断连，必须显式传 confirm=true。对应
        POST /hosts/firewall/operate，body 用 FirewallOperation。

        Args:
            operation: start/stop/restart/disableBanPing/enableBanPing。
            with_docker_restart: 是否同时重启 docker。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "防火墙启停/重启是高危操作（可能导致 SSH 断连），必须显式传 confirm=true。"
            )
        client = await get_client()
        return await client.post("/hosts/firewall/operate", {
            "operation": operation, "withDockerRestart": with_docker_restart,
        })

    # ---- iptables filter 链操作（写，高危） ----

    @mcp.tool()
    async def firewall_filter_operate(
        name: Annotated[FilterChainName, Field(description="链名：1PANEL_INPUT / 1PANEL_OUTPUT / 1PANEL_BASIC")],
        operate: Annotated[FilterOperate, Field(description="操作：init-base/init-forward/init-advance/bind-base/unbind-base/bind/unbind")],
        confirm: Annotated[bool, Field(description="高危操作，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [防火墙] 应用/卸载/初始化 iptables filter 链。

        直接操作底层 iptables 链，错误配置可能断网。必须显式传 confirm=true。对应
        POST /hosts/firewall/filter/operate，body 用 IptablesOp。

        Args:
            name: 目标链名。
            operate: init-base 初始化基础链 / bind 绑定 / unbind 解绑等。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "iptables filter 链操作是高危操作（可能导致网络中断），必须显式传 confirm=true。"
            )
        client = await get_client()
        return await client.post("/hosts/firewall/filter/operate", {
            "name": name, "operate": operate,
        })

    @mcp.tool()
    async def firewall_filter_rule_operate(
        chain: Annotated[FilterChain, Field(description="链名：1PANEL_BASIC/1PANEL_BASIC_BEFORE/1PANEL_INPUT/1PANEL_OUTPUT")],
        operation: Annotated[RuleOperation, Field(description="操作：add 新建 / remove 删除")],
        strategy: Annotated[FilterStrategy, Field(description="策略：accept/drop/reject")],
        protocol: Annotated[Optional[str], Field(description="协议，如 tcp/udp/all")] = None,
        src_ip: Annotated[Optional[str], Field(description="源 IP/CIDR")] = None,
        src_port: Annotated[Optional[int], Field(description="源端口")] = None,
        dst_ip: Annotated[Optional[str], Field(description="目的 IP/CIDR")] = None,
        dst_port: Annotated[Optional[int], Field(description="目的端口")] = None,
        description: Annotated[Optional[str], Field(description="规则备注")] = None,
        id: Annotated[Optional[int], Field(description="规则 ID，删除时定位用")] = None,
        confirm: Annotated[bool, Field(description="高危操作，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [防火墙] 新增/删除 iptables filter 高级规则。

        直接写底层 iptables 规则，错误配置可能断网。必须显式传 confirm=true。对应
        POST /hosts/firewall/filter/rule/operate，body 用 IptablesRuleOp。

        Args:
            chain: 目标链。
            operation: add / remove。
            strategy: accept / drop / reject。
            protocol: 协议。
            src_ip/src_port: 源 IP / 源端口。
            dst_ip/dst_port: 目的 IP / 目的端口。
            description: 规则备注。
            id: 规则 ID（删除时）。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "iptables filter 规则操作是高危操作（可能导致网络中断），必须显式传 confirm=true。"
            )
        client = await get_client()
        body: dict = {"chain": chain, "operation": operation, "strategy": strategy}
        if protocol is not None:
            body["protocol"] = protocol
        if src_ip is not None:
            body["srcIP"] = src_ip
        if src_port is not None:
            body["srcPort"] = src_port
        if dst_ip is not None:
            body["dstIP"] = dst_ip
        if dst_port is not None:
            body["dstPort"] = dst_port
        if description is not None:
            body["description"] = description
        if id is not None:
            body["id"] = id
        return await client.post("/hosts/firewall/filter/rule/operate", body)

    @mcp.tool()
    async def firewall_filter_rule_batch(
        rules: Annotated[list[dict], Field(description="iptables 规则列表，每条结构同 IptablesRuleOp（chain/operation/strategy 必填）")],
        confirm: Annotated[bool, Field(description="高危操作，必须传 true 才执行")] = False,
    ) -> dict:
        """⚠️高危 [防火墙] 批量新增/删除 iptables filter 规则。

        对应 POST /hosts/firewall/filter/rule/batch，body 用 IptablesBatchOperate。

        Args:
            rules: 规则列表，每条至少含 chain/operation/strategy。
            confirm: 必须为 true。
        """
        require_write()
        if not confirm:
            raise ValueError(
                "iptables filter 批量操作是高危操作（可能导致网络中断），必须显式传 confirm=true。"
            )
        client = await get_client()
        return await client.post("/hosts/firewall/filter/rule/batch", {"rules": rules})
