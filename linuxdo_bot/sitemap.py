"""全站枚举器：从 linux.do 的 sitemap 拿到**全站 topic_id 权威清单**。

Discourse 的 sitemap 是分层的：
    /sitemap.xml            → sitemapindex，列出 sitemap_1.xml .. sitemap_N.xml
    /sitemap_{k}.xml        → 每个约 10000 条 <loc>https://linux.do/t/topic/{id}</loc>

实测（2026-07）：43 个子图 × 1 万 ≈ 43 万主题。这是全量采集的入口——
把所有 topic_id 灌进 frontier 表，调度器再按状态逐个采集，天然支持断点续跑。

合规：sitemap 就是网站主动提供给爬虫的索引清单，读它最正当；仍走过盾+限速。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_INDEX_URL = "https://linux.do/sitemap.xml"
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_TOPIC_RE = re.compile(r"/t/(?:[^/]+/)?(\d+)")


class SitemapEnumerator:
    """用注入的 fetcher（BrowserFetcher，过 CF 盾）拉取并解析 sitemap。"""

    def __init__(self, fetcher) -> None:
        self._fetcher = fetcher

    def list_submaps(self) -> list[str]:
        """解析 sitemapindex，返回所有子图 URL。"""
        xml = self._fetcher.get_text(_INDEX_URL)
        locs = _LOC_RE.findall(xml)
        submaps = [u for u in locs if "sitemap" in u and u.endswith(".xml")]
        logger.info("sitemap 索引：%d 个子图", len(submaps))
        return submaps

    def topic_ids_in(self, submap_url: str) -> list[str]:
        """解析一个子图，返回其中的 topic_id 列表（保序、去重）。"""
        xml = self._fetcher.get_text(submap_url)
        ids: list[str] = []
        seen: set[str] = set()
        for loc in _LOC_RE.findall(xml):
            m = _TOPIC_RE.search(loc)
            if m:
                tid = m.group(1)
                if tid not in seen:
                    seen.add(tid)
                    ids.append(tid)
        logger.info("子图 %s：%d 个 topic_id", submap_url.rsplit("/", 1)[-1], len(ids))
        return ids

    def enumerate_all(self, corpus, max_submaps: int | None = None) -> dict:
        """枚举全站（或前 max_submaps 个子图），把 topic_id 灌进 frontier。

        断点续跑：已登记的 topic_id 靠 frontier 的 INSERT OR IGNORE 天然跳过；
        子图进度记在 meta（sitemap_done_submaps），重启从下一个子图继续。
        """
        submaps = self.list_submaps()
        if max_submaps is not None:
            submaps = submaps[:max_submaps]

        done_raw = corpus.get_meta("sitemap_done_submaps", "")
        done = set(done_raw.split("|")) if done_raw else set()

        total_new = 0
        for i, sm in enumerate(submaps, 1):
            if sm in done:
                logger.info("跳过已完成子图 %s", sm)
                continue
            ids = self.topic_ids_in(sm)
            new = corpus.frontier_add(ids)
            total_new += new
            done.add(sm)
            corpus.set_meta("sitemap_done_submaps", "|".join(sorted(done)))
            logger.info("[%d/%d] %s：新增 %d（frontier 累计 pending 见 stats）",
                        i, len(submaps), sm.rsplit("/", 1)[-1], new)

        stats = corpus.frontier_stats()
        return {"submaps": len(submaps), "new_topics": total_new, "frontier": stats}
