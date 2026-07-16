"""基于 Playwright 的浏览器抓取器（用于有 Cloudflare 挑战的站点）。

为什么用真实浏览器：某些站点（如 linux.do）用 Cloudflare 托管挑战，
需要执行挑战 JS 才放行——真实浏览器会像正常用户一样通过。这是「以真实
用户方式访问 robots 允许的公开内容」，而非逆向/伪造。

合规：
    - 仍复用令牌桶限速（构造时传入），不因用浏览器而放松频次；
    - 只访问目标站 robots 允许的公开路径；
    - 首次访问先过挑战、复用同一浏览器上下文（省资源、拿 cookie）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BrowserFetcher:
    """惰性启动的 Playwright 抓取器，返回页面正文文本（通常是 .json）。"""

    def __init__(self, bucket=None, headless: bool = True, timeout_ms: int = 30000,
                 proxy: str | None = None) -> None:
        self._bucket = bucket
        self._headless = headless
        self._timeout = timeout_ms
        # proxy: 如 "http://127.0.0.1:7897"。经 Clash 混合端口出口，用于多 IP 轮换。
        # cf_clearance 绑 IP，故换代理需重启浏览器上下文（见 set_proxy）。
        self._proxy = proxy
        self._pw = None
        self._browser = None
        self._ctx = None

    def _ensure(self) -> None:
        if self._ctx is not None:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        launch_kwargs: dict = {"headless": self._headless}
        if self._proxy:
            launch_kwargs["proxy"] = {"server": self._proxy}
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._ctx = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        logger.info("Playwright 浏览器已启动 (headless=%s, proxy=%s)",
                    self._headless, self._proxy or "直连")

    def set_proxy(self, proxy: str | None) -> None:
        """切换出口代理。因 cf_clearance 绑 IP，换代理必须重启浏览器上下文，
        下次 get_text 会用新代理重新过盾。"""
        if proxy == self._proxy:
            return
        self._teardown()
        self._proxy = proxy

    def get_text(self, url: str, attempts: int = 2) -> str:
        """导航到 url，等待挑战通过，返回页面正文文本。

        偶发的"挑战未在超时内过盾"会当次 reload 重试（attempts 次），
        把单轮成功率从 ~85% 拉到接近 100%，减少 frontier 里 pending 堆积。
        限速只在首次消耗令牌（重试属同一逻辑请求，不额外占额度）。
        """
        if self._bucket is not None:
            self._bucket.acquire()  # 限速：与其他源共用同一套合规约束
        self._ensure()
        page = self._ctx.new_page()
        try:
            last = ""
            for i in range(max(1, attempts)):
                if i == 0:
                    page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
                else:
                    page.reload(wait_until="domcontentloaded", timeout=self._timeout)
                passed = True
                try:
                    # Cloudflare 挑战页标题含 "Just a moment"，等它跳转为真实内容
                    page.wait_for_function(
                        "() => !document.title.includes('Just a moment')",
                        timeout=self._timeout,
                    )
                except Exception:  # noqa: BLE001
                    passed = False
                last = page.inner_text("body")
                # 过盾成功且拿到实际内容（非挑战页）即返回
                if passed and "Just a moment" not in last:
                    return last
                logger.warning("过盾未成功(第%d/%d次): %s", i + 1, attempts, url)
            return last
        finally:
            page.close()

    def _teardown(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = self._browser = self._pw = None

    def close(self) -> None:
        self._teardown()
