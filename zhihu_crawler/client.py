"""采集会话客户端。

把合规内核（robots 门 + 令牌桶限速 + 退避重试）和签名构造串成一个
统一的 fetch 入口。所有出站请求都经过：
    can_fetch(robots) -> acquire(令牌桶) -> 带签名头请求 -> 退避重试
"""
from __future__ import annotations

import logging
import random
from urllib.parse import urlparse

import requests

from .compliance import RobotsGate, TokenBucket, retry_with_backoff
from .config import Config
from .signature import build_signed_headers

logger = logging.getLogger(__name__)


class ComplianceError(Exception):
    """被 robots.txt 禁止时抛出。"""


class ZhihuClient:
    def __init__(self, config: Config, d_c0: str = "") -> None:
        self.config = config
        self.d_c0 = d_c0
        self._user_agents = config.crawler.get("user_agents") or [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]
        self._session = requests.Session()

        c = config.compliance
        self._robots = RobotsGate(
            user_agent="*",
            enabled=c.respect_robots,
        )
        self._bucket = TokenBucket(rate=c.requests_per_second, capacity=c.burst)
        self._timeout = config.crawler.get("timeout", 15)

    def _ua(self) -> str:
        return random.choice(self._user_agents)

    def fetch(self, url: str, signed: bool = False, respect_robots: bool = True) -> requests.Response:
        """合规 fetch：robots 校验 -> 限速 -> (可选)签名 -> 退避重试。

        respect_robots=False 仅用于「官方 API 通道」这类 robots(面向网页索引)
        不适用、但有明确条款授权的场景（见 sources/arxiv.py 的说明）。限速仍生效。
        """
        # 1. robots 门（可按源豁免；豁免须有条款依据并在调用处注明）
        if respect_robots and not self._robots.can_fetch(url):
            raise ComplianceError(f"robots.txt 禁止抓取: {url}")

        # 2. 令牌桶限速（阻塞直到有令牌）
        waited = self._bucket.acquire()
        if waited:
            logger.debug("限速等待 %.2fs", waited)

        # 3. 组装请求头
        ua = self._ua()
        headers = {"user-agent": ua, "accept": "application/json, text/html"}
        if signed:
            parsed = urlparse(url)
            pq = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            headers.update(build_signed_headers(pq, self.d_c0, ua))

        # 4. 带退避重试的实际请求
        c = self.config.compliance

        @retry_with_backoff(
            max_retries=c.max_retries,
            base=c.backoff_base,
            max_delay=c.backoff_max,
            retry_on=(requests.RequestException,),
        )
        def _do() -> requests.Response:
            resp = self._session.get(url, headers=headers, timeout=self._timeout)
            # 429/5xx 视为可重试
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.RequestException(f"HTTP {resp.status_code}")
            return resp

        return _do()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "ZhihuClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
