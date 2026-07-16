"""鲁棒解析器。

面对知乎多变的 DOM 结构（以及防爬可能插入的干扰节点），采用三层策略：
    1. 主选择器（XPath / CSS）
    2. 多重回退选择器（结构变了也能兜住）
    3. 数据清洗 + 校验（去掉干扰节点、空白、异常值）

同时支持解析 JSON API 响应（更稳）和 HTML 页面（回退）。
呼应前端底子：对 DOM/XPath/CSS 的熟悉是这里鲁棒性的来源。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lxml import html as lxml_html

from .models import Answer

logger = logging.getLogger(__name__)

# 已知的干扰/噪声节点特征（防爬有时插入隐藏节点扰乱文本提取）
_NOISE_SELECTORS = [
    ".//style", ".//script", ".//noscript",
    ".//*[contains(@style,'display:none')]",
    ".//*[contains(@style,'display: none')]",
    ".//*[@aria-hidden='true']",
]


def _first_text(node, xpaths: list[str]) -> str:
    """按顺序尝试多个 XPath，返回第一个非空文本（多重回退）。"""
    for xp in xpaths:
        try:
            res = node.xpath(xp)
        except Exception:
            continue
        if not res:
            continue
        val = res[0]
        text = val if isinstance(val, str) else getattr(val, "text_content", lambda: "")()
        text = (text or "").strip()
        if text:
            return text
    return ""


def _strip_noise(element) -> None:
    """就地移除干扰节点。"""
    for sel in _NOISE_SELECTORS:
        for bad in element.xpath(sel):
            bad.getparent().remove(bad) if bad.getparent() is not None else None


def parse_search_api(payload: dict[str, Any] | str) -> list[Answer]:
    """解析知乎搜索 API 的 JSON 响应（首选路径，最稳）。"""
    if isinstance(payload, str):
        payload = json.loads(payload)

    answers: list[Answer] = []
    for item in payload.get("data", []):
        obj = item.get("object") or item
        if obj.get("type") not in (None, "answer", "article"):
            continue
        author = (obj.get("author") or {}).get("name", "") if isinstance(obj.get("author"), dict) else ""
        # 回答的标题在 question.name，文章的标题在 title —— 依次回退
        question = obj.get("question") or {}
        title = (question.get("name") if isinstance(question, dict) else "") or obj.get("title", "")
        answers.append(
            Answer(
                answer_id=str(obj.get("id", "")),
                question_title=title,
                author=author,
                content_html=obj.get("content", "") or obj.get("excerpt", ""),
                voteup_count=int(obj.get("voteup_count", 0) or 0),
                comment_count=int(obj.get("comment_count", 0) or 0),
                url=obj.get("url", ""),
            )
        )
    logger.info("从 API 解析出 %d 条", len(answers))
    return answers


def parse_answer_html(page_html: str, url: str = "") -> Answer | None:
    """从回答页面 HTML 提取（回退路径，用于无 API 或 API 变更时）。"""
    try:
        tree = lxml_html.fromstring(page_html)
    except Exception as exc:
        logger.warning("HTML 解析失败: %s", exc)
        return None

    # 主 + 回退选择器
    title = _first_text(tree, [
        "//h1[contains(@class,'QuestionHeader-title')]/text()",
        "//title/text()",
        "//meta[@property='og:title']/@content",
    ])
    author = _first_text(tree, [
        "//div[contains(@class,'AuthorInfo')]//a[contains(@class,'name')]/text()",
        "//span[contains(@class,'UserLink')]//text()",
        "//meta[@itemprop='author']/@content",
    ])

    # 内容节点：先去噪，再取文本
    content_nodes = tree.xpath(
        "//div[contains(@class,'RichContent-inner')] | //div[contains(@class,'RichText')]"
    )
    content_html = ""
    if content_nodes:
        node = content_nodes[0]
        _strip_noise(node)
        content_html = lxml_html.tostring(node, encoding="unicode")

    voteup = _first_text(tree, [
        "//button[contains(@class,'VoteButton--up')]/@aria-label",
        "//meta[@itemprop='upvoteCount']/@content",
    ])
    voteup_count = int(re.search(r"\d+", voteup).group()) if re.search(r"\d+", voteup) else 0

    answer_id = ""
    m = re.search(r"/answer/(\d+)", url)
    if m:
        answer_id = m.group(1)

    if not (title or content_html):
        return None

    return Answer(
        answer_id=answer_id,
        question_title=title,
        author=author,
        content_html=content_html,
        voteup_count=voteup_count,
        url=url,
    )
