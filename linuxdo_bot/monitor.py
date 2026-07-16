"""监控循环：定时合规采集 linux.do → 关键词匹配 → 分发通知。

分发通过注入的 notifier 回调完成：
    - 真实运行：notifier = TelegramClient.send_message 的包装
    - dry-run  ：notifier = 打印到控制台（无需 TG token 即可端到端验证）
"""
from __future__ import annotations

import html
import logging
import time
from typing import Callable

from zhihu_crawler.client import ZhihuClient
from zhihu_crawler.config import Config as CrawlerConfig
from zhihu_crawler.sources.tgchannel import TgChannelSource

from .config import BotConfig
from .corpus import Corpus
from .matcher import match_any
from .store import Store

logger = logging.getLogger(__name__)

# notifier(chat_id, text) -> None
Notifier = Callable[[str, str], None]


class Monitor:
    """监控循环。主力源 = 官方 TG 频道网页版（轻量、无需盾/浏览器）。

    采集到的每条主题都沉淀进语料库（供 RAG 复用），同时做订阅匹配与推送。
    """

    def __init__(self, config: BotConfig, store: Store, notifier: Notifier,
                 corpus: Corpus | None = None) -> None:
        self.config = config
        self.store = store
        self.notify = notifier
        self.corpus = corpus
        self._stop = False

        cc = CrawlerConfig()
        cc.compliance.requests_per_second = config.requests_per_second
        self._crawler_config = cc

    def _make_source(self, client: ZhihuClient) -> TgChannelSource:
        return TgChannelSource(client)

    def poll_once(self) -> int:
        """采集一轮，返回本轮新推送条数。"""
        subs = self.store.all_subscriptions()        # {chat_id: [kw]}
        user_subs = self.store.all_user_subscriptions()  # {chat_id: [username]}
        pushed = 0
        with ZhihuClient(self._crawler_config) as client:
            source = self._make_source(client)
            try:
                for item in source.fetch("", self.config.fetch_limit):
                    if self.corpus is not None:
                        self.corpus.upsert(item)     # 沉淀进语料库
                    pushed += self._handle_item(item, subs, user_subs)
            finally:
                source.close()
        return pushed

    def _handle_item(self, item, subs: dict[str, list[str]],
                     user_subs: dict[str, list[str]]) -> int:
        tid = item.external_id
        body = item.content_html
        self.store.mark_seen(tid)

        # 收集应通知的 (chat_id, 命中原因)
        targets: dict[str, list[str]] = {}
        for chat_id, keywords in subs.items():
            hits = match_any(keywords, item.title, body)
            if hits:
                targets.setdefault(chat_id, []).extend(hits)
        # 关注用户：作者命中
        author_l = (item.author or "").lower()
        for chat_id, users in user_subs.items():
            if any(u.lower() == author_l for u in users) and author_l:
                targets.setdefault(chat_id, []).append(f"@{item.author}")

        n = 0
        for chat_id, reasons in targets.items():
            if self.store.already_pushed(chat_id, tid):
                continue
            self.notify(chat_id, self._format(item, reasons))
            self.store.mark_pushed(chat_id, tid)
            n += 1
        return n

    @staticmethod
    def _format(item, reasons: list[str]) -> str:
        title = html.escape(item.title)
        author = html.escape(item.author or "?")
        why = html.escape(", ".join(dict.fromkeys(reasons)))  # 去重保序
        return (
            f"🔔 <b>linux.do 命中</b>：{why}\n\n"
            f"<b>{title}</b>\n"
            f"👤 {author}  💬 {item.comment_count}  👁 {item.score}\n"
            f'🔗 <a href="{html.escape(item.url)}">查看主题</a>'
        )

    def run_forever(self) -> None:
        logger.info("监控启动：每 %ds 采集，分类=%s", self.config.poll_interval, self.config.categories)
        while not self._stop:
            try:
                n = self.poll_once()
                logger.info("本轮推送 %d 条", n)
            except Exception as exc:  # noqa: BLE001
                logger.warning("采集轮异常（继续下一轮）: %s", exc)
            # 分段睡眠，便于快速停止
            slept = 0
            while slept < self.config.poll_interval and not self._stop:
                time.sleep(min(2, self.config.poll_interval - slept))
                slept += 2

    def stop(self) -> None:
        self._stop = True
