"""Hacker News 采集源（官方 Firebase API）。

API 文档: https://github.com/HackerNews/API
- 官方公开、文档化的编程 API，无需鉴权，被无数应用使用。
- topstories.json 返回按热度排序的 story id 列表。
- item/{id}.json 返回单条详情。

⚠️ 合规判断（真实工程细节，面试可讲）：
  该 API 部署在 `hacker-news.firebaseio.com`（Firebase 平台），其 robots.txt
  是 **Firebase 的默认全站 Disallow**，面向的是网页索引爬虫；而 HN 官方明确
  把此地址作为**公开编程 API** 提供。二者性质不同：
    - robots 面向网页抓取/索引；
    - 官方文档化 API 是被授权的程序化访问通道。
  因此本源对 API 主机显式豁免 robots（respect_robots=False）并注明依据，
  同时**限速与退避照常生效**，做到透明、克制、可辩护。
"""
from __future__ import annotations

import logging
from typing import Iterator

from .base import Item, Source

logger = logging.getLogger(__name__)

_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsSource(Source):
    name = "hackernews"

    def fetch(self, query: str, limit: int) -> Iterator[Item]:
        # query 支持 top / new / best，默认 top
        listing = {"new": "newstories", "best": "beststories"}.get(query, "topstories")
        # 官方 API 通道，豁免 Firebase 默认 robots（见模块头说明）；限速仍生效
        resp = self.client.fetch(f"{_BASE}/{listing}.json", respect_robots=False)
        ids = resp.json() or []
        logger.info("HN %s: 拿到 %d 个 id，取前 %d", listing, len(ids), limit)

        count = 0
        for hid in ids:
            if count >= limit:
                break
            item = self._fetch_item(hid)
            if item:
                count += 1
                yield item

    def _fetch_item(self, hid: int) -> Item | None:
        try:
            data = self.client.fetch(f"{_BASE}/item/{hid}.json", respect_robots=False).json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HN item %s 获取失败: %s", hid, exc)
            return None
        if not data or data.get("type") not in ("story", "job", "poll"):
            return None

        # HN 的正文可能在 text（Ask HN）或仅有外链 url
        content = data.get("text", "") or ""
        url = data.get("url", "") or f"https://news.ycombinator.com/item?id={hid}"
        return Item(
            source=self.name,
            external_id=str(data.get("id", hid)),
            title=data.get("title", ""),
            author=data.get("by", ""),
            content_html=content,
            url=url,
            score=int(data.get("score", 0) or 0),
            comment_count=int(data.get("descendants", 0) or 0),
            tags=data.get("type", ""),
        )
