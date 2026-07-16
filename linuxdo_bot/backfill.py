"""历史回填：从官方 TG 频道往前翻，把历史主题沉淀进语料库。

断点续跑：进度（已回填到的最小消息 ID）记在语料库 meta 表，
中断后再跑会从上次位置继续，不重复。

用法（见 __main__）：
    python -m linuxdo_bot --backfill --pages 20
"""
from __future__ import annotations

import logging
import time

from zhihu_crawler.client import ZhihuClient
from zhihu_crawler.config import Config as CrawlerConfig
from zhihu_crawler.sources.tgchannel import TgChannelSource

from .config import BotConfig
from .corpus import Corpus

logger = logging.getLogger(__name__)

_PAGE = 15  # TG 频道每页约 15 条


def run_backfill(config: BotConfig, corpus: Corpus, pages: int = 20) -> dict:
    """回填约 pages 页历史。返回统计。"""
    cc = CrawlerConfig()
    cc.compliance.requests_per_second = config.requests_per_second

    # 起点：上次回填游标；没有则用语料库里已知最小消息 ID；再没有则从最新往前
    cursor = corpus.backfill_cursor or corpus.min_msg_id()
    total_new = total = 0
    limit = pages * _PAGE

    with ZhihuClient(cc) as client:
        source = TgChannelSource(client)
        try:
            if cursor:
                logger.info("从消息 ID %s 往前回填约 %d 页…", cursor, pages)
                gen = source.fetch_before(cursor, limit=limit)
            else:
                logger.info("语料库为空，先从最新开始拉 %d 页…", pages)
                gen = source.fetch("", limit=limit)

            min_seen = cursor
            for item in gen:
                total += 1
                if corpus.upsert(item):
                    total_new += 1
                # 跟踪本次回填到的最小消息 ID
                msg = _msg_id(item)
                if msg and (min_seen is None or msg < min_seen):
                    min_seen = msg

            if min_seen:
                corpus.backfill_cursor = min_seen
        finally:
            source.close()

    stats = {"new": total_new, "seen": total, "cursor": corpus.backfill_cursor,
             "corpus_total": corpus.count()}
    logger.info("回填完成：新增 %d / 处理 %d，游标 → %s，语料库累计 %d",
                stats["new"], stats["seen"], stats["cursor"], stats["corpus_total"])
    return stats


def _msg_id(item) -> int | None:
    for part in (item.tags or "").split(","):
        if part.startswith("tg_msg:"):
            v = part.split(":", 1)[1]
            return int(v) if v.isdigit() else None
    return None
