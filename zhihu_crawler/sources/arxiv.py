"""arXiv 采集源（官方 Atom API）。

API 文档: https://info.arxiv.org/help/api/index.html

⚠️ 合规判断（面试可讲的一个真实细节）：
  arXiv 的 robots.txt 对 /api 路径标注 Disallow —— 那是**针对搜索引擎爬虫**
  的索引限制。但 arXiv 的官方 API Terms of Use 明确**授权程序化访问**，
  唯一硬性要求是 **每 3 秒不超过 1 次请求**。
  因此本源：
    1. 走官方 API 端点（而非抓网页），符合其 API 使用条款；
    2. 通过合规客户端强制 ≥3s/请求 的限速；
    3. 在 client 层对该源关闭 robots 拦截（因 robots 面向的是网页索引，
       不适用于官方授权的 API 通道）——并在此注释说明依据，做到透明。
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Iterator

from .base import Item, Source

logger = logging.getLogger(__name__)

_BASE = "http://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivSource(Source):
    name = "arxiv"

    def fetch(self, query: str, limit: int) -> Iterator[Item]:
        # query 作为 arXiv 检索式。多源共用一个 query 时，非 arXiv 语义的词
        # （如 HN 的 top/new/best）回退到默认分类，保证多源采集稳健。
        if ":" in query:
            search = query
        elif re.match(r"^[a-z-]+\.[A-Za-z]+$", query or ""):  # 形如 cs.AI / math.PR
            search = f"cat:{query}"
        else:
            search = "cat:cs.AI"
        url = (
            f"{_BASE}?search_query={search}&max_results={limit}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )
        # arXiv API 是官方授权通道，robots 面向网页索引，此处显式放行并限速
        resp = self.client.fetch(url, respect_robots=False)
        yield from self._parse(resp.text, limit)

    def _parse(self, xml_text: str, limit: int) -> Iterator[Item]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning("arXiv XML 解析失败: %s", exc)
            return
        count = 0
        for entry in root.findall("atom:entry", _NS):
            if count >= limit:
                break
            title = (entry.findtext("atom:title", "", _NS) or "").strip()
            summary = (entry.findtext("atom:summary", "", _NS) or "").strip()
            eid = (entry.findtext("atom:id", "", _NS) or "").strip()
            authors = [
                (a.findtext("atom:name", "", _NS) or "").strip()
                for a in entry.findall("atom:author", _NS)
            ]
            cats = [c.get("term", "") for c in entry.findall("atom:category", _NS)]
            arxiv_id = re.search(r"abs/([^v]+)", eid)
            if not title:
                continue
            count += 1
            yield Item(
                source=self.name,
                external_id=arxiv_id.group(1) if arxiv_id else eid,
                title=re.sub(r"\s+", " ", title),
                author=", ".join(a for a in authors if a),
                content_html=summary,
                url=eid,
                tags=",".join(c for c in cats if c),
            )
