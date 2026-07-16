"""Clash 控制器：把 Clash 的多节点当作"可切换出口 IP 池"。

背景（实测得出，2026-07-11）：
    Clash 是**单一本地代理端口**（如 mixed-port 7897）+ 选中一个节点出口，
    不是"同时 N 个 IP 并行"。所以它不能做真并行，只能**切换出口 IP**：
    通过 Clash 的外部控制 API（`PUT /proxies/{selector}` body={name}）改当前节点。

    实测：切不同落地的节点 → 出口 IP 确实变（5 节点 = 5 个不同 IP）。
    但 CF 的 cf_clearance 绑 IP，每换一个 IP，Playwright 都要重新过盾——
    所以**逐请求换 IP 更慢**（每次重新过盾）。正确用法是**按批轮换**：
    一个 IP 上过盾后连采一批，再切下一个 IP 采下一批。

价值（面试可讲）：
    单 IP 会被 CF 频率冷却（我实测撞到过）。按批轮换把负载分散到多个出口 IP，
    是真实的**稳定性**提升（不是并发提速）。这也是"分布式采集"在只有一台机器 +
    一个 Clash 时的落地形态。

⚠️ 合规边界：
    轮换出口 IP 分散请求，本质是规避目标站的 IP 频率限制。是否用于某站点取决于
    你是否获该站授权；本模块是架构能力实现，请自行把握边界。
"""
from __future__ import annotations

import logging
import time
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


class ClashController:
    """通过 Clash 外部控制 API 管理节点切换。"""

    def __init__(self, base_url: str = "http://127.0.0.1:9097",
                 secret: str = "", timeout: float = 5.0) -> None:
        self.base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        r = requests.get(self.base + path, headers=self._headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def configs(self) -> dict:
        """返回 Clash 运行配置（含各代理端口）。"""
        return self._get("/configs")

    def proxy_port(self) -> int | None:
        """当前可用的 HTTP/混合代理端口（供 Playwright 出口）。"""
        cfg = self.configs()
        # mixed-port 同时支持 http/socks，优先；否则退 http port
        return cfg.get("mixed-port") or cfg.get("port") or None

    def selectors(self) -> dict[str, dict]:
        """返回所有 Selector 类型的策略组（可切换的组）。"""
        data = self._get("/proxies").get("proxies", {})
        return {name: p for name, p in data.items()
                if p.get("type") == "Selector"}

    def node_names(self, exclude_groups: bool = True) -> list[str]:
        """返回真实节点名（过滤掉策略组/内置 DIRECT/REJECT）。"""
        data = self._get("/proxies").get("proxies", {})
        group_types = {"Selector", "URLTest", "Fallback", "LoadBalance", "Relay"}
        builtin = {"DIRECT", "REJECT", "GLOBAL", "PASS", "COMPATIBLE"}
        names = []
        for name, p in data.items():
            if name in builtin:
                continue
            if p.get("type") in group_types:
                continue
            names.append(name)
        return names

    def current(self, selector: str = "GLOBAL") -> str | None:
        """某策略组当前选中的节点。"""
        data = self._get("/proxies").get("proxies", {})
        return (data.get(selector) or {}).get("now")

    def select(self, node: str, selector: str = "GLOBAL") -> bool:
        """把 selector 组切到指定 node。成功返回 True。"""
        url = f"{self.base}/proxies/{quote(selector)}"
        try:
            r = requests.put(url, json={"name": node}, headers=self._headers,
                             timeout=self.timeout)
            ok = r.status_code in (204, 200)
            if ok:
                logger.info("Clash 切换 %s → %s", selector, node)
            else:
                logger.warning("Clash 切换失败 HTTP %d: %s", r.status_code, node)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.warning("Clash 切换异常 %s: %s", node, exc)
            return False

    def egress_ip(self, proxy_port: int | None = None, timeout: float = 8.0,
                  retries: int = 3) -> str | None:
        """经当前 Clash 出口查真实 IP（用中立端点）。用于验证/去重节点。

        切换节点后连接可能短暂未就绪，故对多个端点做多轮重试，
        提高拿到 IP 的成功率（否则 distinct_nodes 会漏掉刚切好的节点）。
        """
        port = proxy_port or self.proxy_port()
        if not port:
            return None
        proxies = {"http": f"http://127.0.0.1:{port}",
                   "https": f"http://127.0.0.1:{port}"}
        endpoints = ("https://api.ipify.org", "http://ip-api.com/line/query",
                     "https://ifconfig.me/ip")
        for attempt in range(max(1, retries)):
            for ep in endpoints:
                try:
                    r = requests.get(ep, proxies=proxies, timeout=timeout)
                    if r.status_code == 200 and r.text.strip():
                        return r.text.strip().splitlines()[0]
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(0.8)  # 端点全轮空，等连接就绪再试
        return None

    def distinct_nodes(self, candidates: list[str], selector: str = "GLOBAL",
                       max_nodes: int = 8, settle: float = 2.0) -> list[dict]:
        """在候选节点里挑出**出口 IP 互不相同**的一批（做 IP 池用）。

        返回 [{node, ip}]。会依次切换并查 IP，去重。这是一次性的"选池"过程，
        跑全站前做一次即可。
        """
        seen_ip: set[str] = set()
        picked: list[dict] = []
        port = self.proxy_port()
        for node in candidates:
            if len(picked) >= max_nodes:
                break
            if not self.select(node, selector):
                continue
            time.sleep(settle)  # 等切换生效
            ip = self.egress_ip(port)
            if ip and ip not in seen_ip:
                seen_ip.add(ip)
                picked.append({"node": node, "ip": ip})
                logger.info("入池节点 %s → %s", node, ip)
        return picked
