"""Telegram 命令处理：把用户消息映射到订阅操作，返回回复文本。

命令：
    /start, /help          帮助
    /sub <关键词>          订阅（支持 空格=AND、|=OR、/正则/）
    /unsub <关键词>        取消订阅
    /list                  查看我的订阅
    /latest [n]           立即拉取最新 n 条（默认 5）
"""
from __future__ import annotations

import html
import logging

from .matcher import match_any
from .store import Store

logger = logging.getLogger(__name__)

HELP = (
    "🤖 <b>linux.do 监控机器人</b>\n\n"
    "定时采集 linux.do 最新主题，命中你的订阅就推送。\n\n"
    "<b>关键词</b>\n"
    "/subscribe <code>关键词</code> — 订阅（空格=且，| =或，/正则/）\n"
    "  例：<code>/subscribe python</code>　<code>/subscribe ai|llm agent</code>\n"
    "/unsubscribe <code>关键词</code> — 取消\n"
    "<b>关注用户</b>\n"
    "/subscribe_user <code>用户名</code> — 该用户发帖就推送\n"
    "/unsubscribe_user <code>用户名</code> — 取消\n"
    "<b>智能搜索</b>\n"
    "/ask <code>问题</code> — AI 搜索社区已有解决方法（论坛搜索的增强版）\n"
    "  例：<code>/ask codex 额度超限怎么办</code>\n"
    "<b>其它</b>\n"
    "/list — 我的订阅\n"
    "/latest [n] — 立即看最新 n 条\n"
    "/quick — 快捷订阅（一键按钮：claude/ai/gemini/公益 等 + 公益大佬）\n"
    "/help — 帮助\n\n"
    "💡 关键词支持正则，如 <code>/subscribe /gpt-?5/</code>"
)


class CommandRouter:
    """无状态命令路由；latest/ask 用注入的回调完成即时采集/问答。"""

    def __init__(self, store: Store, fetch_latest=None, ask_fn=None) -> None:
        self.store = store
        self.fetch_latest = fetch_latest  # () -> list[Item]
        self.ask_fn = ask_fn              # (question) -> str(HTML)

    def handle(self, chat_id: str, text: str) -> str:
        text = (text or "").strip()
        if not text.startswith("/"):
            return "发送 /help 查看用法。"
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lstrip("/").lower()
        arg = arg.strip()

        if cmd in ("start", "help"):
            return HELP
        if cmd in ("subscribe", "sub"):
            return self._sub(chat_id, arg)
        if cmd in ("unsubscribe", "unsub"):
            return self._unsub(chat_id, arg)
        if cmd in ("subscribe_user", "sub_user"):
            return self._sub_user(chat_id, arg)
        if cmd in ("unsubscribe_user", "unsub_user"):
            return self._unsub_user(chat_id, arg)
        if cmd == "list":
            return self._list(chat_id)
        if cmd == "latest":
            return self._latest(chat_id, arg)
        if cmd == "ask":
            return self._ask(arg)
        if cmd == "quick":
            return "QUICK"   # 特殊标记：主循环据此发带 inline 键盘的消息
        return "未知命令，发送 /help 查看用法。"

    def handle_callback(self, chat_id: str, data: str) -> str:
        """处理 inline 按钮点击。data 形如 'sub:关键词' / 'subuser:用户名'。"""
        action, _, val = data.partition(":")
        if action == "sub":
            ok = self.store.add_subscription(chat_id, val)
            return f"已订阅 {val}" if ok else f"已订阅过 {val}"
        if action == "subuser":
            ok = self.store.add_user_subscription(chat_id, val)
            return f"已关注 {val}" if ok else f"已关注过 {val}"
        return "未知操作"

    def _ask(self, arg: str) -> str:
        if not arg:
            return "用法：/ask 你的问题　例：/ask codex 额度超限怎么办"
        if self.ask_fn is None:
            return "问答功能未启用。"
        try:
            return self.ask_fn(arg)
        except Exception:  # noqa: BLE001
            return "问答出错了，请稍后再试。"

    def _sub_user(self, chat_id: str, arg: str) -> str:
        if not arg:
            return "用法：/subscribe_user 用户名　例：/subscribe_user neo"
        ok = self.store.add_user_subscription(chat_id, arg)
        u = arg.lstrip("@")
        return f"✅ 已关注用户：<code>{u}</code>，TA 发帖会通知你" if ok else \
               f"你已关注过：<code>{u}</code>"

    def _unsub_user(self, chat_id: str, arg: str) -> str:
        if not arg:
            return "用法：/unsubscribe_user 用户名"
        ok = self.store.remove_user_subscription(chat_id, arg)
        return "✅ 已取消关注" if ok else "未找到该关注（用 /list 查看）"

    def _sub(self, chat_id: str, arg: str) -> str:
        if not arg:
            return "用法：/sub 关键词　例：/sub python 或 /sub ai|llm agent"
        ok = self.store.add_subscription(chat_id, arg)
        return f"✅ 已订阅：<code>{html.escape(arg)}</code>" if ok else \
               f"你已订阅过：<code>{html.escape(arg)}</code>"

    def _unsub(self, chat_id: str, arg: str) -> str:
        if not arg:
            return "用法：/unsub 关键词"
        ok = self.store.remove_subscription(chat_id, arg)
        return "✅ 已取消订阅" if ok else "未找到该订阅（用 /list 查看）"

    def _list(self, chat_id: str) -> str:
        kws = self.store.list_subscriptions(chat_id)
        users = self.store.list_user_subscriptions(chat_id)
        if not kws and not users:
            return "你还没有订阅。用 /subscribe 关键词 或 /subscribe_user 用户名 开始。"
        parts = []
        if kws:
            parts.append("📋 <b>关键词（%d）</b>\n" % len(kws) +
                         "\n".join(f"• <code>{html.escape(k)}</code>" for k in kws))
        if users:
            parts.append("👥 <b>关注用户（%d）</b>\n" % len(users) +
                         "\n".join(f"• <code>{html.escape(u)}</code>" for u in users))
        return "\n\n".join(parts)

    def _latest(self, chat_id: str, arg: str) -> str:
        if self.fetch_latest is None:
            return "该命令暂不可用。"
        try:
            n = min(int(arg), 10) if arg.isdigit() else 5
        except ValueError:
            n = 5
        items = self.fetch_latest(n)
        if not items:
            return "暂时没拿到数据，稍后再试。"
        kws = self.store.list_subscriptions(chat_id)
        lines = []
        for it in items:
            hit = match_any(kws, it.title) if kws else []
            mark = "🔔" if hit else "•"
            lines.append(f'{mark} <a href="{html.escape(it.url)}">{html.escape(it.title[:50])}</a>'
                         f"（💬{it.comment_count}）")
        return "🆕 <b>linux.do 最新</b>\n" + "\n".join(lines)
