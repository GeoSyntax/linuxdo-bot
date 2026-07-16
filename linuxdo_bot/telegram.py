"""极简 Telegram Bot API 客户端（仅用 requests，本地部署零重依赖）。

只实现所需：getUpdates（长轮询收命令）+ sendMessage（推送）。
不引 python-telegram-bot 等重型异步框架，降低本地部署门槛。
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org") -> None:
        self.token = token
        self.base = f"{api_base.rstrip('/')}/bot{token}"
        self._session = requests.Session()

    def _call(self, method: str, params: dict | None = None, timeout: int = 40) -> dict:
        r = self._session.post(f"{self.base}/{method}", json=params or {}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"TG API {method} 失败: {data}")
        return data.get("result", {})

    def get_me(self) -> dict:
        return self._call("getMe", timeout=15)

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        """长轮询拉取更新。offset=上次最大 update_id+1。"""
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        try:
            return self._call("getUpdates", params, timeout=timeout + 10)
        except requests.RequestException as exc:
            logger.warning("getUpdates 网络异常: %s", exc)
            return []

    def send_message(self, chat_id: str | int, text: str, parse_mode: str = "HTML",
                     disable_preview: bool = False,
                     inline_keyboard: list[list[dict]] | None = None) -> None:
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_preview,
        }
        if inline_keyboard:
            params["reply_markup"] = {"inline_keyboard": inline_keyboard}
        try:
            self._call("sendMessage", params, timeout=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("向 %s 发送失败: %s", chat_id, exc)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        """应答 inline 按钮点击（消除 TG 端的加载转圈）。"""
        try:
            self._call("answerCallbackQuery",
                       {"callback_query_id": callback_id, "text": text}, timeout=15)
        except Exception as exc:  # noqa: BLE001
            logger.warning("answerCallback 失败: %s", exc)
