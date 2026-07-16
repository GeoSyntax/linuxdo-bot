"""linux.do 采集源（Discourse 论坛）。

linux.do 是基于 **Discourse** 的中文技术社区。Discourse 的一个官方特性：
几乎任何页面 URL 加 `.json` 就返回该页的结构化数据（前端自身取数方式）。

⚠️ 合规判断（实测依据，面试可讲）：
  1. **robots.txt 实测允许** `/latest.json`、`/categories.json`、`/t/*.json`、
     `/c/` 等路径（与知乎全禁相反）——合规基础成立；
  2. 站点前置 **Cloudflare 托管挑战**，普通 requests / TLS 指纹伪装均被 403；
     需**真实浏览器执行挑战 JS** 才放行 —— 故本源用 Playwright（BrowserFetcher）。
     这是"以真实用户方式访问 robots 允许的公开内容"，非逆向/伪造签名。
  3. 仍走令牌桶限速，克制频次，不给社区服务器造成压力。

产出统一 Item：主题标题、发帖人、回复数(当 comment_count)、浏览数(当 score)、
分类标签、以及主题详情页的正文摘要（可选，二跳 /t/{slug}/{id}.json）。
"""
from __future__ import annotations

import json
import logging
from typing import Iterator

from .base import Item, Source

logger = logging.getLogger(__name__)

_BASE = "https://linux.do"


class LinuxDoSource(Source):
    name = "linuxdo"

    def __init__(self, client, fetcher=None) -> None:
        super().__init__(client)
        # 复用 client 的令牌桶做限速；浏览器抓取器惰性启动
        from .browser_fetcher import BrowserFetcher
        self._fetcher = fetcher or BrowserFetcher(bucket=getattr(client, "_bucket", None))

    def fetch(self, query: str, limit: int) -> Iterator[Item]:
        # query 支持 latest / top / 或分类 slug（如 develop）
        listing = query if query in ("latest", "top", "new", "unread") else "latest"
        if query and query not in ("latest", "top", "new", "unread"):
            url = f"{_BASE}/c/{query}.json"       # 按分类
        else:
            url = f"{_BASE}/{listing}.json"       # 按列表
        logger.info("linux.do 采集: %s", url)

        text = self._fetcher.get_text(url)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("linux.do 返回非 JSON（可能未过挑战），前120字: %s", text[:120])
            return

        topics = (data.get("topic_list") or {}).get("topics", [])
        users = {u["id"]: u.get("username", "") for u in data.get("users", [])}
        count = 0
        for t in topics:
            if count >= limit:
                break
            # 找发帖人：优先带 "Original" 标记的 poster；否则取第一个（Discourse
            # 默认 posters[0] 即楼主），标记文案可能本地化故做双重回退
            author = ""
            posters = t.get("posters", [])
            for p in posters:
                if "Original" in (p.get("description") or ""):
                    author = users.get(p.get("user_id"), "")
                    break
            if not author and posters:
                author = users.get(posters[0].get("user_id"), "")
            # tags 可能是字符串或 {name:..} 字典，统一转字符串
            tag_names = []
            for tag in (t.get("tags") or []):
                if isinstance(tag, dict):
                    tag_names.append(tag.get("name", ""))
                elif isinstance(tag, str):
                    tag_names.append(tag)
            count += 1
            yield Item(
                source=self.name,
                external_id=str(t.get("id", "")),
                title=t.get("title", ""),
                author=author,
                content_html=t.get("excerpt", "") or "",
                url=f"{_BASE}/t/topic/{t.get('id')}",
                score=int(t.get("views", 0) or 0),
                comment_count=int(t.get("posts_count", 0) or 0),
                tags=",".join(n for n in tag_names if n),
            )

    def fetch_topic_detail(self, topic_id: str) -> str:
        """二跳取主题详情，返回首帖正文 HTML（用于更精准的关键词匹配/推送）。

        Discourse: /t/{id}.json 的 post_stream.posts[0].cooked 即首帖渲染后 HTML。
        robots 同样允许 /t/*.json。失败返回空串（不打断流程）。
        """
        try:
            text = self._fetcher.get_text(f"{_BASE}/t/{topic_id}.json")
            data = json.loads(text)
        except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            logger.warning("linux.do 主题 %s 详情获取失败: %s", topic_id, exc)
            return ""
        posts = (data.get("post_stream") or {}).get("posts", [])
        return posts[0].get("cooked", "") if posts else ""

    def fetch_topic_full(self, topic_id: str) -> dict | None:
        """全站采集用：取 /t/{id}.json 的结构化完整字段。

        返回 dict（title/category_id/reply_count/views/author/body_html/
        posted_at），失败返回 None（调用方据此标记 failed 重试）。
        """
        try:
            text = self._fetcher.get_text(f"{_BASE}/t/{topic_id}.json")
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("linux.do 主题 %s 返回非 JSON（未过盾）", topic_id)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("linux.do 主题 %s 详情获取失败: %s", topic_id, exc)
            return None

        # 主题已删除/不存在：Discourse 返回 {errors:[...], error_type:"not_found"}。
        # 这是终态（不该重试），用特殊标记告知调度器直接跳过，省下限速额度。
        if data.get("error_type") == "not_found" or data.get("errors"):
            return {"_gone": True}

        posts = (data.get("post_stream") or {}).get("posts", [])
        first = posts[0] if posts else {}
        return {
            "title": data.get("title", ""),
            "category_id": data.get("category_id"),
            # Discourse: posts_count 含首帖，楼层数=回复数=posts_count-1
            "reply_count": max(0, int(data.get("posts_count", 1) or 1) - 1),
            "views": int(data.get("views", 0) or 0),
            "author": first.get("username", ""),
            "body_html": first.get("cooked", ""),
            "posted_at": data.get("created_at", ""),
        }

    def close(self) -> None:
        self._fetcher.close()
