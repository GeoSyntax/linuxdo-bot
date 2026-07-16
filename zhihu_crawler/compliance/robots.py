"""robots.txt 遵守。

用标准库 urllib.robotparser 拉取并解析目标站点的 robots.txt，
对每个待抓取 URL 做 can_fetch 校验。带缓存，避免重复请求 robots。

合规优先：无法获取 robots 时，默认「保守拒绝」还是「放行」可配置，
本项目默认放行但记录告警（因为知乎公开页面通常允许，且拉不到 robots
往往是网络问题而非禁止），生产中可切换为默认拒绝。
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


class RobotsGate:
    """按域名缓存 robots 规则，判定某 URL 是否允许抓取。"""

    def __init__(
        self,
        user_agent: str = "*",
        enabled: bool = True,
        fail_open: bool = True,
        cache_ttl: float = 3600.0,
    ) -> None:
        self.user_agent = user_agent
        self.enabled = enabled
        self.fail_open = fail_open  # 拉不到 robots 时是否放行
        self.cache_ttl = cache_ttl
        # domain -> (parser, fetched_at)
        self._cache: dict[str, tuple[RobotFileParser | None, float]] = {}

    def _get_parser(self, domain: str) -> RobotFileParser | None:
        now = time.time()
        cached = self._cache.get(domain)
        if cached and now - cached[1] < self.cache_ttl:
            return cached[0]

        parser = RobotFileParser()
        robots_url = f"{domain}/robots.txt"
        parser.set_url(robots_url)
        try:
            parser.read()
            logger.debug("已加载 robots: %s", robots_url)
        except Exception as exc:  # 网络/解析异常
            logger.warning("拉取 robots 失败 %s: %s", robots_url, exc)
            parser = None
        self._cache[domain] = (parser, now)
        return parser

    def can_fetch(self, url: str) -> bool:
        """判断该 URL 是否允许抓取。"""
        if not self.enabled:
            return True

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        domain = f"{parsed.scheme}://{parsed.netloc}"

        parser = self._get_parser(domain)
        if parser is None:
            # 拉不到 robots
            return self.fail_open

        allowed = parser.can_fetch(self.user_agent, url)
        if not allowed:
            logger.info("robots 禁止抓取，跳过: %s", url)
        return allowed

    def crawl_delay(self, url: str) -> float | None:
        """读取 robots 中的 Crawl-delay（若有），供限速器参考。"""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._get_parser(domain)
        if parser is None:
            return None
        try:
            delay = parser.crawl_delay(self.user_agent)
            return float(delay) if delay is not None else None
        except Exception:
            return None
