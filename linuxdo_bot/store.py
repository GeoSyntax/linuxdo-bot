"""机器人存储层（SQLite）：订阅管理 + 已推送去重 + 主题缓存。

三张表：
    subscriptions  (chat_id, keyword)      —— 每个用户订阅的关键词
    seen           (topic_id)              —— 已见主题，避免重复通知
    pushed         (chat_id, topic_id)     —— 已向某用户推过某主题，避免重复推
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    chat_id  TEXT NOT NULL,
    keyword  TEXT NOT NULL,
    created  REAL,
    PRIMARY KEY (chat_id, keyword)
);
CREATE TABLE IF NOT EXISTS user_subscriptions (
    chat_id  TEXT NOT NULL,
    username TEXT NOT NULL,
    created  REAL,
    PRIMARY KEY (chat_id, username)
);
CREATE TABLE IF NOT EXISTS seen (
    topic_id  TEXT PRIMARY KEY,
    first_seen REAL
);
CREATE TABLE IF NOT EXISTS pushed (
    chat_id   TEXT NOT NULL,
    topic_id  TEXT NOT NULL,
    pushed_at REAL,
    PRIMARY KEY (chat_id, topic_id)
);
"""


class Store:
    def __init__(self, db_path: str | Path) -> None:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：监控线程与主线程共用（配锁）
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------------- 订阅 ----------------
    def add_subscription(self, chat_id: str, keyword: str) -> bool:
        keyword = keyword.strip()
        if not keyword:
            return False
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO subscriptions (chat_id, keyword, created) VALUES (?,?,?)",
                    (str(chat_id), keyword, time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # 已订阅

    def remove_subscription(self, chat_id: str, keyword: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM subscriptions WHERE chat_id=? AND keyword=?",
                (str(chat_id), keyword.strip()),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_subscriptions(self, chat_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT keyword FROM subscriptions WHERE chat_id=? ORDER BY created",
                (str(chat_id),),
            ).fetchall()
        return [r[0] for r in rows]

    def all_subscriptions(self) -> dict[str, list[str]]:
        """返回 {chat_id: [keywords]}，供监控循环批量匹配。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id, keyword FROM subscriptions"
            ).fetchall()
        out: dict[str, list[str]] = {}
        for chat_id, kw in rows:
            out.setdefault(chat_id, []).append(kw)
        return out

    # ---------------- 关注用户订阅 ----------------
    def add_user_subscription(self, chat_id: str, username: str) -> bool:
        username = username.strip().lstrip("@")
        if not username:
            return False
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO user_subscriptions (chat_id, username, created) VALUES (?,?,?)",
                    (str(chat_id), username, time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def remove_user_subscription(self, chat_id: str, username: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM user_subscriptions WHERE chat_id=? AND username=?",
                (str(chat_id), username.strip().lstrip("@")),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_user_subscriptions(self, chat_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT username FROM user_subscriptions WHERE chat_id=? ORDER BY created",
                (str(chat_id),),
            ).fetchall()
        return [r[0] for r in rows]

    def all_user_subscriptions(self) -> dict[str, list[str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT chat_id, username FROM user_subscriptions"
            ).fetchall()
        out: dict[str, list[str]] = {}
        for chat_id, u in rows:
            out.setdefault(chat_id, []).append(u)
        return out

    # ---------------- 去重 ----------------
    def is_seen(self, topic_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM seen WHERE topic_id=?", (str(topic_id),)
            ).fetchone()
        return row is not None

    def mark_seen(self, topic_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO seen (topic_id, first_seen) VALUES (?,?)",
                (str(topic_id), time.time()),
            )
            self._conn.commit()

    def already_pushed(self, chat_id: str, topic_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM pushed WHERE chat_id=? AND topic_id=?",
                (str(chat_id), str(topic_id)),
            ).fetchone()
        return row is not None

    def mark_pushed(self, chat_id: str, topic_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO pushed (chat_id, topic_id, pushed_at) VALUES (?,?,?)",
                (str(chat_id), str(topic_id), time.time()),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
