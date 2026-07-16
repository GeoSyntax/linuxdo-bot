"""存储层：SQLite（默认，零配置）/ MySQL（可选，展示 DB 能力）。

统一 upsert 接口，按内容指纹去重。SQLite 用标准库即可运行，
MySQL 分支演示连接池思路（对应 JD 的 MySQL 要求）。
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from .config import Config
from .models import Answer

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    fingerprint     TEXT PRIMARY KEY,
    answer_id       TEXT,
    question_title  TEXT,
    author          TEXT,
    content_html    TEXT,
    content_markdown TEXT,
    voteup_count    INTEGER,
    comment_count   INTEGER,
    url             TEXT,
    sentiment       TEXT,
    is_cleaned      INTEGER,
    crawled_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_answer_id ON answers(answer_id);

CREATE TABLE IF NOT EXISTS items (
    fingerprint      TEXT PRIMARY KEY,
    source           TEXT,
    external_id      TEXT,
    title            TEXT,
    author           TEXT,
    content_html     TEXT,
    content_markdown TEXT,
    url              TEXT,
    score            INTEGER,
    comment_count    INTEGER,
    tags             TEXT,
    sentiment        TEXT,
    is_cleaned       INTEGER,
    crawled_at       REAL
);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
"""


class Storage:
    """存储抽象。默认 SQLite。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.backend = config.storage.backend
        if self.backend == "sqlite":
            db_path = config.project_root / config.storage.sqlite_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        elif self.backend == "mysql":
            self._conn = self._connect_mysql()
        else:
            raise ValueError(f"未知存储后端: {self.backend}")

    def _connect_mysql(self):
        try:
            import pymysql
        except ImportError as e:
            raise RuntimeError("MySQL 后端需要 pip install PyMySQL") from e
        m = self.config.storage.mysql
        conn = pymysql.connect(
            host=m.get("host", "127.0.0.1"),
            port=int(m.get("port", 3306)),
            user=m.get("user", "root"),
            password=m.get("password", ""),
            database=m.get("database", "zhihu"),
            charset="utf8mb4",
            autocommit=True,
        )
        # MySQL 建表（简化，生产中走迁移工具）
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS answers ("
                "fingerprint VARCHAR(64) PRIMARY KEY, answer_id VARCHAR(64),"
                "question_title TEXT, author VARCHAR(255), content_html LONGTEXT,"
                "content_markdown LONGTEXT, voteup_count INT, comment_count INT,"
                "url TEXT, sentiment VARCHAR(16), is_cleaned TINYINT, crawled_at DOUBLE"
                ") DEFAULT CHARSET=utf8mb4"
            )
        return conn

    def save(self, answer: Answer) -> bool:
        """保存一条（按指纹 upsert）。返回是否为新插入。"""
        d = answer.to_dict()
        d["fingerprint"] = answer.fingerprint
        d["is_cleaned"] = int(answer.is_cleaned)
        cols = [
            "fingerprint", "answer_id", "question_title", "author",
            "content_html", "content_markdown", "voteup_count",
            "comment_count", "url", "sentiment", "is_cleaned", "crawled_at",
        ]
        values = [d[c] for c in cols]

        if self.backend == "sqlite":
            placeholders = ",".join("?" * len(cols))
            sql = f"INSERT OR REPLACE INTO answers ({','.join(cols)}) VALUES ({placeholders})"
            cur = self._conn.execute(sql, values)
            self._conn.commit()
            return cur.rowcount > 0
        else:  # mysql
            placeholders = ",".join(["%s"] * len(cols))
            updates = ",".join(f"{c}=VALUES({c})" for c in cols if c != "fingerprint")
            sql = (
                f"INSERT INTO answers ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
            with self._conn.cursor() as cur:
                cur.execute(sql, values)
            return True

    def save_many(self, answers: Iterable[Answer]) -> int:
        n = 0
        for a in answers:
            if a.is_valid():
                self.save(a)
                n += 1
            else:
                logger.warning("跳过不合格数据 %s: %s", a.answer_id, a.validate())
        return n

    # ---------------- 通用多源 Item 存储 ----------------
    _ITEM_COLS = [
        "fingerprint", "source", "external_id", "title", "author",
        "content_html", "content_markdown", "url", "score",
        "comment_count", "tags", "sentiment", "is_cleaned", "crawled_at",
    ]

    def save_item(self, item) -> bool:
        """保存一条多源 Item（按指纹 upsert）。"""
        d = item.to_dict()
        d["fingerprint"] = item.fingerprint
        d["is_cleaned"] = int(item.is_cleaned)
        values = [d[c] for c in self._ITEM_COLS]
        if self.backend == "sqlite":
            ph = ",".join("?" * len(self._ITEM_COLS))
            self._conn.execute(
                f"INSERT OR REPLACE INTO items ({','.join(self._ITEM_COLS)}) VALUES ({ph})",
                values,
            )
            self._conn.commit()
            return True
        ph = ",".join(["%s"] * len(self._ITEM_COLS))
        updates = ",".join(f"{c}=VALUES({c})" for c in self._ITEM_COLS if c != "fingerprint")
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO items ({','.join(self._ITEM_COLS)}) VALUES ({ph}) "
                f"ON DUPLICATE KEY UPDATE {updates}",
                values,
            )
        return True

    def save_items(self, items) -> int:
        n = 0
        for it in items:
            if it.is_valid():
                self.save_item(it)
                n += 1
            else:
                logger.warning("跳过不合格 Item %s: %s", it.external_id, it.validate())
        return n

    def count(self, table: str = "answers") -> int:
        table = "items" if table == "items" else "answers"
        if self.backend == "sqlite":
            return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
