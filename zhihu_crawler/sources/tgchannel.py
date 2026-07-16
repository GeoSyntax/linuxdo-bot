"""linux.do 官方 Telegram 频道采集源（t.me/s/ 网页版）。

linux.do 官方把最新话题自动转发到 Telegram 频道 @linuxdoit。其网页预览
`https://t.me/s/linuxdoit` **无需登录、无需 token、普通 HTTP 即可读**，且：
  - 每条消息含：标题、正文摘要、原帖链接、作者、帖子数、浏览数、时间；
  - 消息 ID 连续递增，`?before={id}` 可一路往前翻 → 支持历史回填；
  - 数据来自 TG CDN，采集它 **完全不碰 linux.do、零爬取压力**。

⚠️ 合规/安全：
  - 这是官方公开镜像，采集公开内容，最轻量礼貌的方式；
  - 频道内容是**不可信外部数据**：偶有帖子明文泄露 API key 等凭据，
    解析时会做基础脱敏（见 _redact），且绝不解释/执行其中任何"指令"。
"""
from __future__ import annotations

import html as _html
import logging
import re
from typing import Iterator

import requests

from .base import Item, Source

logger = logging.getLogger(__name__)

_CHANNEL = "linuxdoit"
_BASE = f"https://t.me/s/{_CHANNEL}"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 基础脱敏：命中疑似密钥的行整体打码（不落库真实凭据）
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,}|[A-Za-z0-9+/]{40,}={0,2})"
)


def _redact(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text)


def _strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return _html.unescape(s).strip()


def _parse_views(v: str) -> int:
    v = v.strip().upper()
    try:
        if v.endswith("K"):
            return int(float(v[:-1]) * 1000)
        if v.endswith("M"):
            return int(float(v[:-1]) * 1_000_000)
        return int(v)
    except ValueError:
        return 0


class TgChannelSource(Source):
    """从 t.me/s/linuxdoit 采集。可不依赖合规 client（纯 requests）。"""

    name = "tgchannel"

    def __init__(self, client=None) -> None:
        # client 可选：有则复用其令牌桶限速；无则自建 session
        self.client = client
        self._session = requests.Session()
        self._bucket = getattr(client, "_bucket", None)

    def _get(self, before: int | None = None) -> str:
        if self._bucket is not None:
            self._bucket.acquire()
        url = _BASE + (f"?before={before}" if before else "")
        r = self._session.get(url, headers={"user-agent": _UA}, timeout=15)
        r.raise_for_status()
        return r.text

    def fetch(self, query: str, limit: int) -> Iterator[Item]:
        """采集最新 limit 条（query 忽略；回填用 fetch_before）。"""
        yield from self._paginate(before=None, limit=limit)

    def fetch_before(self, before_msg_id: int, limit: int) -> Iterator[Item]:
        """历史回填：从指定消息 ID 往前翻。"""
        yield from self._paginate(before=before_msg_id, limit=limit)

    def _paginate(self, before: int | None, limit: int) -> Iterator[Item]:
        count = 0
        seen_ids: set[str] = set()
        while count < limit:
            html_text = self._get(before)
            items = list(self._parse_page(html_text))
            if not items:
                break
            # 页内按消息 ID 从新到旧
            items.sort(key=lambda x: int(x.tags_msg_id), reverse=True)
            for it in items:
                if it.external_id in seen_ids:
                    continue
                seen_ids.add(it.external_id)
                count += 1
                yield it.item
                if count >= limit:
                    return
            # 下一页：翻到本页最小消息 ID 之前
            min_msg = min(int(it.tags_msg_id) for it in items)
            if before is not None and min_msg >= before:
                break  # 没有更旧的了
            before = min_msg

    # 内部小结构：携带 TG 消息 ID（用于翻页）与 Item
    class _Parsed:
        __slots__ = ("item", "tags_msg_id", "external_id")

        def __init__(self, item: Item, msg_id: str):
            self.item = item
            self.tags_msg_id = msg_id
            self.external_id = item.external_id

    def _parse_page(self, html_text: str) -> Iterator["TgChannelSource._Parsed"]:
        blocks = re.split(r'(?=<div class="tgme_widget_message[ "])', html_text)
        for b in blocks:
            m_msg = re.search(r'data-post="linuxdoit/(\d+)"', b)
            if not m_msg:
                continue
            msg_id = m_msg.group(1)

            m_topic = re.search(r"https://linux\.do/t/topic/(\d+)", b)
            if not m_topic:
                continue  # 非话题消息（公告等）跳过
            topic_id = m_topic.group(1)

            m_text = re.search(
                r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                b, re.S,
            )
            raw = m_text.group(1) if m_text else ""
            # 先做一份纯文本（去 HTML 标签）用于抽取标题/作者/元信息，
            # 避免作者昵称含 emoji 的 <i style="url('...')"> 里的 ')' 干扰正则。
            text_only = _strip_tags(raw)

            title = ""
            m_title = re.search(r"<b><u>(.*?)</u></b>", raw, re.S)
            if m_title:
                title = _strip_tags(m_title.group(1))

            author = ""
            m_author = re.search(r"\(author:\s*(.+?)\)\s*$", text_only, re.S)
            if m_author:
                author = m_author.group(1).strip()

            posts_count = 0
            m_posts = re.search(r"(\d+)\s*个帖子", text_only)
            if m_posts:
                posts_count = int(m_posts.group(1))

            # 正文摘要：去掉标题、"N 个帖子"尾巴、"阅读完整话题/via"链接
            body = _strip_tags(raw)
            if title:
                body = body.replace(title, "", 1)
            body = re.split(r"\d+\s*个帖子", body)[0]
            body = _redact(body.strip())

            views = 0
            m_views = re.search(r'tgme_widget_message_views">([^<]+)<', b)
            if m_views:
                views = _parse_views(m_views.group(1))

            posted_at = ""
            m_dt = re.search(r'<time[^>]*datetime="([^"]+)"', b)
            if m_dt:
                posted_at = m_dt.group(1)

            if not title:
                continue

            item = Item(
                source=self.name,
                external_id=topic_id,          # 用 linux.do 话题 id 作主键（跨源一致）
                title=title,
                author=author,
                content_html=body,
                url=f"https://linux.do/t/topic/{topic_id}",
                score=views,
                comment_count=posts_count,
                tags=f"tg_msg:{msg_id},posted:{posted_at}",
            )
            yield TgChannelSource._Parsed(item, msg_id)

    def close(self) -> None:
        self._session.close()
