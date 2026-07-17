"""FlareSolverr 采集器：一次浏览器过盾 → cookie 复用 → 纯 HTTP 高速采集。

FlareSolverr 是一个 Docker 化的 HTTP 代理服务（默认端口 8191），内部运行
undetected-chromedriver 解决 Cloudflare 挑战，返回 HTML 和 cookies。

本 fetcher 的策略：
    1. 首次请求某域名 → 调 FlareSolverr 过盾 → 拿到 cf_clearance cookie + UA
    2. 后续请求用 requests.Session + 该 cookie 纯 HTTP 发起（~50 请求/秒）
    3. 检测到 CF 挑战页（cookie 过期）→ 重新调 FlareSolverr 过盾
    4. 如果 FlareSolverr 不可用 → 抛异常让调用方降级

相比 Playwright：首次过盾速度相当，后续请求快 10-50 倍（不需要开浏览器页签）。
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Cloudflare 挑战页特征
_CF_MARKERS = ("Just a moment", "Checking your browser", "cf-browser-verification")


class FlareSolverrFetcher:
    """基于 FlareSolverr 的 CF 过盾 + cookie 复用采集器。

    鸭子接口与 BrowserFetcher 一致：get_text(url) -> str, close()。
    """

    def __init__(
        self,
        flaresolverr_url: str = "http://127.0.0.1:8191/v1",
        bucket=None,
        proxy: str | None = None,
        timeout: int = 30,
    ) -> None:
        self._fs_url = flaresolverr_url
        self._bucket = bucket
        self._proxy = proxy
        self._timeout = timeout * 1000  # FlareSolverr 用毫秒

        self._session = requests.Session()
        self._ua: str | None = None
        self._solved_domains: set[str] = set()
        self._cookie_expires: dict[str, float] = {}  # domain -> timestamp

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc or url

    def _solve_cf(self, url: str) -> bool:
        """调 FlareSolverr 过盾，拿到 cookies + UA 注入 session。

        返回 True 表示过盾成功。
        """
        domain = self._domain(url)
        logger.info("FlareSolverr 过盾: %s", domain)

        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": self._timeout,
        }
        if self._proxy:
            payload["proxy"] = {"url": self._proxy}

        try:
            resp = requests.post(
                self._fs_url,
                json=payload,
                timeout=(10, self._timeout / 1000 + 30),
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("FlareSolverr 请求失败（服务是否运行？）: %s", exc)
            return False

        data = resp.json()
        if data.get("status") != "ok":
            logger.error("FlareSolverr 返回错误: %s", data.get("message", data))
            return False

        solution = data.get("solution", {})
        cookies = solution.get("cookies", [])
        user_agent = solution.get("userAgent", "")

        if not cookies:
            logger.warning("FlareSolverr 返回空 cookies，过盾可能失败")
            return False

        # 注入 cookies 到 session
        for c in cookies:
            self._session.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", domain),
                path=c.get("path", "/"),
            )

        if user_agent:
            self._ua = user_agent
            self._session.headers["User-Agent"] = user_agent

        self._solved_domains.add(domain)
        self._cookie_expires[domain] = time.time() + 1800  # 30 分钟有效
        logger.info("FlareSolverr 过盾成功: %s (cookies=%d, ua=%s)",
                    domain, len(cookies), user_agent[:50] if user_agent else "无")
        return True

    def _is_cf_challenge(self, text: str, status_code: int = 200) -> bool:
        """检测是否被 CF 拦截。"""
        if status_code in (403, 503):
            return True
        return any(marker in text for marker in _CF_MARKERS)

    def _invalidate(self, domain: str) -> None:
        """清除某域名的过盾状态，下次请求重新过盾。"""
        self._solved_domains.discard(domain)
        self._cookie_expires.pop(domain, None)
        try:
            self._session.cookies.clear(domain=domain)
        except KeyError:
            pass

    def set_proxy(self, proxy: str | None) -> None:
        """切换代理。因 cf_clearance 绑 IP，换代理需重新过盾。"""
        if proxy == self._proxy:
            return
        self._proxy = proxy
        # 清除所有过盾状态
        self._solved_domains.clear()
        self._cookie_expires.clear()
        self._session.cookies.clear()
        logger.info("FlareSolverr 切换代理: %s，清除所有 cookie", proxy)

    def get_text(self, url: str, attempts: int = 2) -> str:
        """获取 URL 内容。先尝试 cookie 复用，失败则重新过盾。"""
        if self._bucket is not None:
            self._bucket.acquire()

        domain = self._domain(url)

        # 如果该域名未过盾或 cookie 已过期，先过盾
        if domain not in self._solved_domains or time.time() > self._cookie_expires.get(domain, 0):
            if not self._solve_cf(url):
                raise ConnectionError(f"FlareSolverr 过盾失败: {url}")

        last = ""
        for i in range(max(1, attempts)):
            try:
                resp = self._session.get(url, timeout=15)
                last = resp.text
                status = resp.status_code

                if not self._is_cf_challenge(last, status):
                    return last

                logger.warning("cookie 过期或 CF 拦截(第%d/%d次): %s (status=%d)",
                               i + 1, attempts, url, status)
                # 重新过盾
                self._invalidate(domain)
                if not self._solve_cf(url):
                    raise ConnectionError(f"FlareSolverr 重新过盾失败: {url}")

            except requests.RequestException as exc:
                logger.warning("请求异常(第%d/%d次): %s - %s", i + 1, attempts, url, exc)
                if i == attempts - 1:
                    raise
                time.sleep(1)

        return last

    def close(self) -> None:
        """释放资源。"""
        self._session.close()
        self._solved_domains.clear()
        self._cookie_expires.clear()
