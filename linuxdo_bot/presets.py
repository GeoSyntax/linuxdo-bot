"""快捷预置：常用关键词 + 公益大佬用户名。

用户可通过 inline 键盘一键订阅，无需手打。可按需增删。
"""
from __future__ import annotations

# 快捷关键词（对齐参考 bot 的内置词 + 常见热点；均支持后续正则订阅）
QUICK_KEYWORDS: list[str] = [
    "claude", "ai", "gemini", "gpt", "codex", "grok", "公益", "开源",
]

# 公益大佬预置用户名（linux.do 上常做公益分享的用户；示例占位，按实际补充）
# 说明：这里放的是公开的社区用户名，用于"关注该用户发帖"的快捷入口。
CHARITY_USERS: list[str] = [
    "neo",          # 站长（示例）
    # 可继续补充你确认的公益大佬用户名
]


def keyword_buttons() -> list[list[dict]]:
    """构造 inline 键盘（每行 3 个），callback_data = 'sub:关键词'。"""
    rows, row = [], []
    for kw in QUICK_KEYWORDS:
        row.append({"text": f"➕ {kw}", "callback_data": f"sub:{kw}"})
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def charity_buttons() -> list[list[dict]]:
    rows, row = [], []
    for u in CHARITY_USERS:
        row.append({"text": f"👤 {u}", "callback_data": f"subuser:{u}"})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows
