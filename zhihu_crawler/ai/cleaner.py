"""AI 内容清洗管道。

把爬到的复杂富文本回答（含图文/代码/公式，可能夹带广告灌水）交给 LLM：
    1. 结构化清洗：HTML -> 干净 Markdown（保留代码块/列表，去广告灌水）
    2. 情感标注：positive / neutral / negative

对 LLM 输出做鲁棒 JSON 解析，解析失败时回退到规则模式，保证管道不断流。
"""
from __future__ import annotations

import json
import logging
import re

from ..models import Answer
from .providers import LLMProvider, RuleProvider, get_provider

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个内容清洗助手。用户会给你一段知乎回答的原始 HTML/文本。
请完成两件事并**只输出 JSON**（不要额外解释）：
1. markdown: 把内容转成干净的 Markdown，保留代码块、列表、重点；删除广告、
   引流（加微信/关注公众号/扫码等）、灌水和无意义寒暄。
2. sentiment: 对内容整体情感做判断，取值 positive / neutral / negative。

输出格式严格为：{"markdown": "...", "sentiment": "..."}"""


class ContentCleaner:
    def __init__(self, config) -> None:
        self.config = config
        self.provider: LLMProvider = get_provider(config)
        self._fallback = RuleProvider()
        logger.info("AI 清洗使用 provider: %s", self.provider.name)

    def _parse_output(self, raw: str) -> dict:
        """鲁棒解析 LLM 输出的 JSON（容忍 ```json 包裹、前后噪声）。"""
        text = raw.strip()
        # 去掉 ```json ... ``` 围栏
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试抠出第一个 {...}
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        raise ValueError("无法解析 LLM 输出为 JSON")

    def clean_text(self, content_html: str) -> tuple[str, str]:
        """清洗单段内容，返回 (markdown, sentiment)。"""
        user = f"请清洗以下内容：\n```\n{content_html}\n```"
        try:
            raw = self.provider.chat(_SYSTEM_PROMPT, user)
            data = self._parse_output(raw)
            markdown = str(data.get("markdown", "")).strip()
            sentiment = str(data.get("sentiment", "neutral")).strip().lower()
            if sentiment not in ("positive", "neutral", "negative"):
                sentiment = "neutral"
            if not markdown:
                raise ValueError("markdown 为空")
            return markdown, sentiment
        except Exception as exc:
            logger.warning("LLM 清洗失败(%s)，回退规则模式", exc)
            raw = self._fallback.chat(_SYSTEM_PROMPT, user)
            data = json.loads(raw)
            return data["markdown"], data["sentiment"]

    def clean_answer(self, answer: Answer) -> Answer:
        """就地清洗一条 Answer 并打标。"""
        source = answer.content_html or answer.content_markdown
        if not source:
            answer.is_cleaned = True
            return answer
        markdown, sentiment = self.clean_text(source)
        answer.content_markdown = markdown
        answer.sentiment = sentiment
        answer.is_cleaned = True
        return answer

    def clean_batch(self, answers: list[Answer]) -> list[Answer]:
        return [self.clean_answer(a) for a in answers]

    def clean_item(self, item):
        """就地清洗一条多源 Item（鸭子类型：任何带 content_html 的对象）。"""
        source = item.content_html or item.content_markdown
        if not source:
            item.is_cleaned = True
            return item
        markdown, sentiment = self.clean_text(source)
        item.content_markdown = markdown
        item.sentiment = sentiment
        item.is_cleaned = True
        return item
