"""WARP 采集器：经 Cloudflare WARP 代理直连（可能免 CF 挑战）+ 降级链。

Cloudflare WARP（1.1.1.1）的出口 IP 是 CF 自己的 IP 段。CF 通常不对自家
IP 发起托管挑战，因此通过 WARP 代理发请求可能直接拿到数据，无需过盾。

降级链：WARP 直连失败 → FlareSolverr 过盾 → BrowserFetcher 真浏览器。
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_CF_MARKERS = ("Just a moment", "Checking your browser", "cf-browser-verification")


class WARPFetcher:
    """经 WARP 代理的 HTTP 采集器，带 FlareSolverr/BrowserFetcher 降级。

    鸭子接口与 BrowserFetcher 一致：get_text(url) -> str, close()。
    """

    def __init__(
        self,
        warp_proxy: str = "socks5://127.0.0.1:40000",
        bucket=None,
        timeout: int = 15,
        fallback_fetcher=None,
    ) -> None:
        self._warp_proxy = warp_proxy
        self._bucket = bucket
        self._timeout = timeout
        self._fallback = fallback_fetcher

        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self._session.proxies = {
            "http": warp_proxy,
            "https": warp_proxy,
        }

    def _is_cf_challenge(self, text: str, status_code: int = 200) -> bool:
        if status_code in (403, 503):
            return True
        return any(marker in text for marker in _CF_MARKERS)

    def set_proxy(self, proxy: str | None) -> None:
        """切换 WARP 代理地址。"""
        if proxy == self._warp_proxy:
            return
        self._warp_proxy = proxy
        self._session.proxies = {"http": proxy, "https": proxy}
        logger.info("WARP 切换代理: %s", proxy)

    def get_text(self, url: str, attempts: int = 2) -> str:
        """经 WARP 代理获取 URL 内容。CF 挑战时降级到 fallback fetcher。"""
        if self._bucket is not None:
            self._bucket.acquire()

        try:
            resp = self._session.get(url, timeout=self._timeout)
            text = resp.text

            # WARP 直连成功（没遇到 CF 挑战）
            if not self._is_cf_challenge(text, resp.status_code):
                return text

            logger.info("WARP 遇到 CF 挑战，降级到 fallback: %s", url)

        except requests.RequestException as exc:
            logger.warning("WARP 请求失败，降级到 fallback: %s - %s", url, exc)

        # 降级
        if self._fallback is not None:
            return self._fallback.get_text(url, attempts=attempts)

        raise ConnectionError(
            f"WARP 请求被 CF 拦截且无 fallback fetcher。"
            f"请配置 FLARESOLVERR_URL 或改用 playwright 模式。"
        )

    def close(self) -> None:
        self._session.close()
        if self._fallback is not None:
            self._fallback.close()
