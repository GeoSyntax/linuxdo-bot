"""源适配器基类与统一数据模型。"""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Iterator

from ..client import ZhihuClient  # 复用合规采集客户端（robots+限速+退避）


@dataclass
class Item:
    """跨源统一的内容条目。"""

    source: str                    # 来源标识：hackernews / arxiv / ...
    external_id: str               # 源内唯一 id
    title: str
    author: str = ""
    content_html: str = ""         # 原始内容
    content_markdown: str = ""     # AI 清洗后
    url: str = ""
    score: int = 0                 # 赞/分数
    comment_count: int = 0
    tags: str = ""                 # 分类/标签，逗号分隔
    sentiment: str = ""
    is_cleaned: bool = False
    crawled_at: float = field(default_factory=time.time)

    @property
    def fingerprint(self) -> str:
        base = f"{self.source}:{self.external_id}" if self.external_id else (self.url or self.title)
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    def validate(self) -> list[str]:
        problems = []
        if not self.external_id:
            problems.append("缺少 external_id")
        if not self.title:
            problems.append("缺少 title")
        if self.score < 0:
            problems.append("score 为负")
        return problems

    def is_valid(self) -> bool:
        return not self.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Source(ABC):
    """采集源接口。子类实现 fetch，产出 Item。

    统一通过传入的 ZhihuClient 发请求，从而复用合规内核
    （robots 遵守 + 令牌桶限速 + 退避重试）——不因换源而放松合规。
    """

    name: str = "base"

    def __init__(self, client: ZhihuClient) -> None:
        self.client = client

    @abstractmethod
    def fetch(self, query: str, limit: int) -> Iterator[Item]:
        """按查询词采集至多 limit 条，逐条 yield Item。"""
        raise NotImplementedError
