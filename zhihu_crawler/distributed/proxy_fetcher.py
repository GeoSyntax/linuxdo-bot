"""通过代理池取数的采集客户端（闭环：用完把结果回报给池子）。

这是 ProxyPool 的使用方：每次请求向池子 acquire 一个健康代理，计时发起
请求，据结果（成功 / 失败 / 被封）调用 report 更新池子健康视图。多个采集
worker 共用一个 ProxyPool，就构成"多出口 IP 并行采集"的分布式基础。

⚠️ 合规边界（与 proxy_pool.py 一致）：
    用代理池分散请求会规避目标站的 IP 频率限制。本模块是**架构能力实现**，
    默认对接中立/允许的端点（如 httpbin）做验证。用于某具体站点前，须确认
    你已获该站授权；个人作品集建议坚持单 IP 合规限速。

封禁识别（可配）：把哪些 HTTP 状态视为"该代理被目标站封了"是站点相关的，
    默认 403/429/503（常见的风控/挑战/限流信号）。识别到即让该代理进隔离。
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

import requests

from .proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

_DEFAULT_BAN_CODES = (403, 429, 503)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ProxyFetcher:
    """用代理池发 HTTP 请求，自动回报健康状态、失败换代理重试。"""

    def __init__(
        self,
        pool: ProxyPool,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        ban_codes: Iterable[int] = _DEFAULT_BAN_CODES,
    ) -> None:
        self.pool = pool
        self.timeout = timeout
        self.max_retries = max_retries
        self.ban_codes = set(ban_codes)
        self._session = requests.Session()

    def get(self, url: str) -> requests.Response | None:
        """经代理取 url。失败自动换代理重试，全失败返回 None。"""
        for attempt in range(1, self.max_retries + 1):
            proxy = self.pool.acquire()
            if proxy is None:
                logger.warning("代理池无可用代理（都在冷却/封禁），放弃")
                return None

            proxies = {"http": proxy, "https": proxy}
            started = time.monotonic()
            try:
                resp = self._session.get(
                    url, proxies=proxies, timeout=self.timeout,
                    headers={"user-agent": _UA},
                )
            except Exception as exc:  # noqa: BLE001 网络层失败：超时/拒绝/代理挂了
                latency = time.monotonic() - started
                logger.warning("代理请求异常(第%d次) %s: %s", attempt, url, exc)
                self.pool.report(proxy, ok=False, latency=latency)
                continue

            latency = time.monotonic() - started
            if resp.status_code in self.ban_codes:
                # 目标站封了这个出口 IP：隔离该代理，换下一个重试
                logger.warning("代理 %s 触发封禁信号 HTTP %d", proxy, resp.status_code)
                self.pool.report(proxy, ok=False, latency=latency, banned=True)
                continue

            # 2xx/3xx/4xx(非封禁) 都算这个代理"通"了——它把请求送到了目标站
            self.pool.report(proxy, ok=True, latency=latency)
            return resp

        logger.warning("URL 重试 %d 次仍失败：%s", self.max_retries, url)
        return None

    def close(self) -> None:
        self._session.close()
