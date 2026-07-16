"""数据模型：采集结果的结构化表示 + 校验。"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Answer:
    """一条知乎回答/内容的结构化模型。"""

    answer_id: str
    question_title: str
    author: str
    content_html: str = ""          # 原始富文本
    content_markdown: str = ""      # AI 清洗后的 Markdown
    voteup_count: int = 0
    comment_count: int = 0
    url: str = ""
    sentiment: str = ""             # AI 情感标签：positive/neutral/negative
    is_cleaned: bool = False        # 是否已过 AI 清洗
    crawled_at: float = field(default_factory=time.time)

    @property
    def fingerprint(self) -> str:
        """内容指纹，用于去重（answer_id 优先，缺失时用内容 hash）。"""
        base = self.answer_id or (self.url or self.content_html[:200])
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    def validate(self) -> list[str]:
        """字段校验，返回问题列表（空则合格）。对应 JD『校验』要求。"""
        problems: list[str] = []
        if not self.answer_id:
            problems.append("缺少 answer_id")
        if not self.question_title:
            problems.append("缺少 question_title")
        if not (self.content_html or self.content_markdown):
            problems.append("内容为空")
        if self.voteup_count < 0:
            problems.append("voteup_count 为负")
        return problems

    def is_valid(self) -> bool:
        return not self.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
