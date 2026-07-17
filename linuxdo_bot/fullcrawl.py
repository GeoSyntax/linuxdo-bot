"""全站采集调度器：把 linux.do 全站主题系统性地采集进语料库。

设计（对应 JD 的"分布式爬虫/大规模采集"能力）：

    ① 枚举：sitemap（43 子图 × 1万）→ 全站 topic_id 权威清单 → frontier 入队
    ② 调度：frontier 表按 status 取任务（pending → detail_done），
            断点续跑（重启从 pending 继续），可平行扩展到多 worker/Redis
    ③ 采集：逐主题 /t/{id}.json 取结构化全文（标题/分类/楼层/正文），
            全程复用合规内核（令牌桶限速 + 退避）+ Playwright 过 CF 盾
    ④ 存储：upsert 进 documents，frontier 标记 detail_done

两级策略：
    - 元数据快扫（可选）：latest.json 翻页，30 主题/请求，快速铺开近期主题
    - 详情精采：/t/{id}.json，1 主题/请求，取全文（供 RAG/搜索）

规模现实：全站约 43 万主题，合规限速下无法一次跑完。本调度器的价值是
**可断点续跑、可分布式扩展**，跑出有意义的量级即可证明架构 scale。
"""
from __future__ import annotations

import logging
import time

from zhihu_crawler.client import ZhihuClient
from zhihu_crawler.config import Config as CrawlerConfig
from zhihu_crawler.sources.base import Item
from zhihu_crawler.sources.linuxdo import LinuxDoSource, create_fetcher

from .config import BotConfig
from .corpus import Corpus
from .sitemap import SitemapEnumerator

logger = logging.getLogger(__name__)


class FullCrawler:
    """全站采集调度器。单机、断点续跑；分布式扩展见类末注释。"""

    def __init__(self, config: BotConfig, corpus: Corpus) -> None:
        self.config = config
        self.corpus = corpus
        cc = CrawlerConfig()
        cc.compliance.requests_per_second = config.requests_per_second
        self._crawler_config = cc
        self._fetcher_kwargs = dict(
            fetch_mode=config.fetch_mode,
            flaresolverr_url=config.flaresolverr_url,
            warp_proxy=config.warp_proxy,
            headless=config.headless,
        )

    # ---------------- ① 枚举 ----------------
    def enumerate_site(self, max_sitemaps: int | None = None) -> dict:
        """拉 sitemap，把全站 topic_id 登记进 frontier。返回统计。

        枚举本身的断点续跑（子图级进度）由 SitemapEnumerator.enumerate_all
        通过 meta 记录，重启从下一个未完成子图继续。
        """
        with ZhihuClient(self._crawler_config) as client:
            fetcher = create_fetcher(bucket=getattr(client, "_bucket", None),
                                     **self._fetcher_kwargs)
            source = LinuxDoSource(client, fetcher=fetcher)
            try:
                enum = SitemapEnumerator(fetcher)
                result = enum.enumerate_all(self.corpus, max_submaps=max_sitemaps)
            finally:
                source.close()
        stats = {"discovered": result["new_topics"], "new": result["new_topics"],
                 "submaps": result["submaps"], "frontier": result["frontier"]}
        logger.info("枚举完成：子图 %d，新增主题 %d，frontier=%s",
                    result["submaps"], result["new_topics"], result["frontier"])
        return stats

    # ---------------- ③ 详情精采 ----------------
    def crawl_details(self, limit: int, max_attempts: int = 3) -> dict:
        """从 frontier 取 pending 主题，逐个取 /t/{id}.json 全文入库。

        断点续跑：只处理 status=pending；失败累加 attempts，超限标 failed。
        """
        claimed = self.corpus.frontier_claim(limit, status="pending")
        if not claimed:
            logger.info("frontier 无 pending 任务（可能已全部完成或未枚举）")
            return {"processed": 0, "ok": 0, "failed": 0, "gone": 0,
                    "corpus_total": self.corpus.count(),
                    "frontier": self.corpus.frontier_stats()}

        ok = failed = gone = 0
        with ZhihuClient(self._crawler_config) as client:
            fetcher = create_fetcher(bucket=getattr(client, "_bucket", None),
                                     **self._fetcher_kwargs)
            source = LinuxDoSource(client, fetcher=fetcher)
            try:
                for tid in claimed:
                    try:
                        detail = source.fetch_topic_full(tid)
                        # 主题已删除/不存在：终态，直接标记 gone 跳过（不占重试额度）
                        if detail and detail.get("_gone"):
                            self.corpus.frontier_mark(tid, "gone")
                            gone += 1
                            continue
                        if not detail or not detail.get("title"):
                            raise ValueError("空详情")
                        # 先 upsert 基本 Item（保证 documents 有行），再回写详情字段
                        self.corpus.upsert(Item(
                            source="linuxdo_full",
                            external_id=tid,
                            title=detail["title"],
                            author=detail.get("author", ""),
                            content_html=detail.get("body_html", ""),
                            url=f"https://linux.do/t/topic/{tid}",
                            score=int(detail.get("views", 0) or 0),
                            comment_count=int(detail.get("reply_count", 0) or 0),
                        ))
                        self.corpus.upsert_detail(
                            tid,
                            body=detail.get("body_html", ""),
                            category_id=detail.get("category_id"),
                            reply_count=detail.get("reply_count"),
                        )
                        self.corpus.frontier_mark(tid, "detail_done")
                        ok += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("主题 %s 采集失败: %s", tid, exc)
                        # 失败：累加 attempts。超过 max_attempts 标 failed（不再重试），
                        # 否则回 pending 下轮重试，避免坏主题无限占用队列。
                        attempts = self.corpus.frontier_attempts(tid) + 1
                        next_status = "failed" if attempts >= max_attempts else "pending"
                        self.corpus.frontier_mark(tid, next_status, bump_attempt=True)
                        failed += 1
            finally:
                source.close()

        stats = {"processed": len(claimed), "ok": ok, "failed": failed,
                 "gone": gone, "corpus_total": self.corpus.count(),
                 "frontier": self.corpus.frontier_stats()}
        logger.info("详情采集：处理 %d，成功 %d，失败 %d，失效 %d，语料库累计 %d",
                    len(claimed), ok, failed, gone, stats["corpus_total"])
        return stats

    def run(self, detail_limit: int, enumerate_first: bool = True,
            max_sitemaps: int | None = None) -> dict:
        """完整流程：枚举（可选）→ 详情采集一批。"""
        if enumerate_first and not self.corpus.frontier_stats():
            self.enumerate_site(max_sitemaps=max_sitemaps)
        return self.crawl_details(detail_limit)


# ─────────────────────────────────────────────────────────────
# 分布式扩展说明（面试可讲）：
#   当前 frontier 用 SQLite 单表，单机断点续跑。要扩到多机：
#   1. frontier_claim 改为 Redis 的 RPOPLPUSH（原子取任务 + 处理中队列），
#      避免多 worker 抢同一任务；处理完从"处理中"删除，超时未删则重回待爬。
#   2. 去重用已有的布隆过滤器（distributed/dedup.py），跨 worker 共享。
#   3. 采集层无状态，可 N 个 worker 并行；每 worker 独立令牌桶 + 全局限速。
#   4. 存储换 MySQL（已在 storage.py 预留），支撑全量规模并发写。
#   Scrapy-Redis 工程（scrapy_project/）即这套思路的框架化实现。
# ─────────────────────────────────────────────────────────────
