"""关键词匹配引擎。

支持的订阅语法（对用户直观，够用且不过度）：
    python              普通词，标题或正文含即匹配（默认大小写不敏感）
    python django       空格分隔 = AND，需全部命中
    python|golang       | 分隔 = OR，命中其一即可
    /pytho[nz]/         用 / 包裹 = 正则（进阶用户）
组合示例：  ai|llm agent   →  (含 ai 或 llm) 且 含 agent
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Keyword:
    raw: str

    def matches(self, text: str) -> bool:
        return _match(self.raw, text)


def _match(pattern: str, text: str) -> bool:
    text_l = text.lower()
    # 正则模式：/.../
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        try:
            return re.search(pattern[1:-1], text, re.I) is not None
        except re.error:
            return False
    # AND：按空格拆，每段都要命中（每段本身可含 OR）
    and_parts = [p for p in pattern.split() if p]
    if not and_parts:
        return False
    for part in and_parts:
        if not _match_or(part, text_l):
            return False
    return True


def _match_or(part: str, text_l: str) -> bool:
    """单个 AND 分量，内部可含 | 表示 OR。"""
    for alt in part.split("|"):
        alt = alt.strip().lower()
        if alt and alt in text_l:
            return True
    return False


def match_any(keywords: list[str], *texts: str) -> list[str]:
    """返回命中的关键词列表（对多段文本做或匹配，如标题+正文）。"""
    blob = "\n".join(t for t in texts if t)
    return [kw for kw in keywords if _match(kw, blob)]
