"""FlareSolverr 采集器：通过 FlareSolverr 会话复用浏览器 → 高速采集。

FlareSolverr 是一个 Docker 化的 HTTP 服务（默认端口 8191），内部运行
undetected-chromedriver。核心优化：用 session 复用浏览器实例，避免每次
请求都启动新浏览器。

策略：
    1. 创建持久 session → FlareSolverr 内部复用浏览器上下文
    2. 每个请求走 FlareSolverr request.get（内部浏览器导航，自动过 CF）
    3. session 内浏览器上下文持续复用，cookie 自动续期
    4. 比纯 Playwright 快：FlareSolverr 用 undetected-chromedriver，反检测更强
"""
from __future__ import annotations

import logging
import re
import uuid

import requests

logger = logging.getLogger(__name__)


def _strip_html_wrapper(text: str) -> str:
    """FlareSolverr 通过浏览器访问 .json 端点时，JSON 被包在 <html><body><pre> 里。
    提取其中的纯文本内容。"""
    m = re.search(r"<pre[^>]*>(.+?)</pre>", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def _strip_html_wrapper(text: str) -> str:
    """FlareSolverr 通过浏览器访问 .json 端点时，JSON 被包在 <html><body><pre> 里。
    提取其中的纯文本内容。"""
    m = re.search(r"<pre[^>]*>(.+?)</pre>", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def _strip_html_wrapper(text: str) -> str:
    """FlareSolverr 通过浏览器访问 .json 端点时，JSON 被包在 <html><body><pre> 里。
    提取其中的纯文本内容。"""
    m = re.search(r"<pre[^>]*>(.+?)</pre>", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def _strip_html_wrapper(text: str) -> str:
    """FlareSolverr 通过浏览器访问 .json 端点时，JSON 被包在 <html><body><pre> 里。
    提取其中的纯文本内容。"""
    m = re.search(r"<pre[^>]*>(.+?)</pre>", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def _strip_html_wrapper(text: str) -> str:
    """FlareSolverr 通过浏览器访问 .json 端点时，JSON 被包在 <html><body><pre> 里。
    提取其中的纯文本内容。"""
    m = re.search(r"<pre[^>]*>(.+?)</pre>", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


class FlareSolverrFetcher:
    """基于 FlareSolverr 会话的 CF 过盾采集器。

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
        self._session_id: str | None = None
        self._http = requests.Session()

    def _ensure_session(self) -> str:
        """确保 FlareSolverr session 存在，返回 session_id。"""
        if self._session_id:
            return self._session_id
        self._session_id = f"linuxdo-{uuid.uuid4().hex[:8]}"
        try:
            resp = self._http.post(self._fs_url, json={
                "cmd": "sessions.create",
                "session": self._session_id,
            }, timeout=30)
            data = resp.json()
            if data.get("status") == "ok":
                logger.info("FlareSolverr session 创建: %s", self._session_id)
            else:
                logger.warning("FlareSolverr session 创建失败: %s", data.get("message"))
                self._session_id = None
        except requests.RequestException as exc:
            logger.error("FlareSolverr 不可达: %s", exc)
            self._session_id = None
        return self._session_id

    def get_text(self, url: str, attempts: int = 2) -> str:
        """通过 FlareSolverr 获取 URL 内容。"""
        if self._bucket is not None:
            self._bucket.acquire()

        session = self._ensure_session()
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": self._timeout,
        }
        if session:
            payload["session"] = session
        if self._proxy:
            payload["proxy"] = {"url": self._proxy}

        for i in range(max(1, attempts)):
            try:
                resp = self._http.post(
                    self._fs_url, json=payload,
                    timeout=(10, self._timeout / 1000 + 60),
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") == "ok":
                    solution = data.get("solution", {})
                    html = solution.get("response", "")
                    status = solution.get("status", 200)
                    if status in (403, 503) and "Just a moment" in html:
                        logger.warning("FlareSolverr CF 未过(第%d/%d次): %s",
                                       i + 1, attempts, url)
                        # session 无效时重建
                        if session:
                            self._destroy_session()
                            session = self._ensure_session()
                            if session:
                                payload["session"] = session
                        continue
                    # FlareSolverr 浏览器返回的 JSON 页面被 <html><body><pre> 包裹，需提取
                    html = _strip_html_wrapper(html)
                    # FlareSolverr 浏览器返回的 JSON 页面被 <html><body><pre> 包裹，需提取
                    html = _strip_html_wrapper(html)
                    # FlareSolverr 浏览器返回的 JSON 页面被 <html><body><pre> 包裹，需提取
                    html = _strip_html_wrapper(html)
                    # FlareSolverr 浏览器返回的 JSON 页面被 <html><body><pre> 包裹，需提取
                    html = _strip_html_wrapper(html)
                    return html
                else:
                    logger.error("FlareSolverr 错误: %s", data.get("message"))
                    if i == attempts - 1:
                        raise ConnectionError(f"FlareSolverr 失败: {data.get('message')}")
            except requests.RequestException as exc:
                logger.warning("FlareSolverr 请求异常(第%d/%d): %s",
                               i + 1, attempts, exc)
                if i == attempts - 1:
                    raise

        return ""

    def _destroy_session(self) -> None:
        if not self._session_id:
            return
        try:
            self._http.post(self._fs_url, json={
                "cmd": "sessions.destroy",
                "session": self._session_id,
            }, timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._session_id = None

    def set_proxy(self, proxy: str | None) -> None:
        if proxy == self._proxy:
            return
        self._destroy_session()
        self._proxy = proxy

    def close(self) -> None:
        self._destroy_session()
        self._http.close()
