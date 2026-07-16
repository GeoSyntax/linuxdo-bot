"""语料库：持久化采集到的 linux.do 主题文档，供推送与 RAG 共用。

设计：
    documents  主题文档（按 topic_id 去重 upsert）
    meta       键值元数据（记录回填进度，支持断点续跑）

这是"知识层"的地基：阶段1只做文档存储；阶段2的 RAG 会在此表上加向量索引。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    topic_id      TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    body          TEXT,
    author        TEXT,
    url           TEXT,
    score         INTEGER,
    comment_count INTEGER,
    posted_at     TEXT,
    tg_msg_id     INTEGER,
    source        TEXT,
    fetched_at    REAL,
    embedded      INTEGER DEFAULT 0,  -- 供 RAG 标记是否已向量化
    category      TEXT,               -- 分类 slug/名（全站采集补充）
    category_id   INTEGER,            -- Discourse 分类 id
    reply_count   INTEGER,            -- 楼层数（详情采集补充，区别于 posts_count）
    detail_fetched INTEGER DEFAULT 0  -- 是否已取过 /t/{id}.json 全文
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 采集边界表（frontier）：全站 topic_id 的待爬/已爬状态。
-- 这是全站采集的核心：sitemap 枚举写入 topic_id，调度器按 status 取任务，
-- 支持断点续跑（重启从 pending 继续）与分布式（多 worker 抢占 pending）。
CREATE TABLE IF NOT EXISTS frontier (
    topic_id    TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',  -- pending / meta_done / detail_done / failed
    attempts    INTEGER DEFAULT 0,
    updated_at  REAL,
    discovered_at REAL
);
"""

# 索引单独建：必须在 _migrate() 补齐列之后执行，否则旧库缺列会报错。
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_docs_msg  ON documents(tg_msg_id);
CREATE INDEX IF NOT EXISTS idx_docs_emb  ON documents(embedded);
CREATE INDEX IF NOT EXISTS idx_docs_cat  ON documents(category_id);
CREATE INDEX IF NOT EXISTS idx_docs_det  ON documents(detail_fetched);
CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(status);
"""


def _parse_tag(tags: str, key: str) -> str:
    """从 'tg_msg:123,posted:...' 里取某个键。"""
    for part in (tags or "").split(","):
        if part.startswith(key + ":"):
            return part[len(key) + 1:]
    return ""


class Corpus:
    def __init__(self, db_path: str | Path) -> None:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript(_SCHEMA)  # 建表（旧库已存在则跳过）
        self._migrate()                     # 给旧库补齐新列
        self._conn.executescript(_INDEXES)  # 补列后再建索引，避免缺列报错
        self._conn.commit()

    def _migrate(self) -> None:
        """安全迁移：给旧库补齐新增列（幂等，忽略已存在）。"""
        cols = {
            "category": "TEXT",
            "category_id": "INTEGER",
            "reply_count": "INTEGER",
            "detail_fetched": "INTEGER DEFAULT 0",
        }
        existing = {
            r[1] for r in self._conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        for name, decl in cols.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")

    def upsert(self, item) -> bool:
        """写入/更新一篇文档。返回 True 表示新插入。"""
        tags = getattr(item, "tags", "") or ""
        msg_id = _parse_tag(tags, "tg_msg")
        posted = _parse_tag(tags, "posted")
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM documents WHERE topic_id=?", (item.external_id,)
            ).fetchone()
            is_new = cur is None
            self._conn.execute(
                """INSERT INTO documents
                   (topic_id,title,body,author,url,score,comment_count,
                    posted_at,tg_msg_id,source,fetched_at,embedded)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,COALESCE(
                       (SELECT embedded FROM documents WHERE topic_id=?),0))
                   ON CONFLICT(topic_id) DO UPDATE SET
                     title=excluded.title, body=excluded.body,
                     score=excluded.score, comment_count=excluded.comment_count,
                     fetched_at=excluded.fetched_at""",
                (
                    item.external_id, item.title, item.content_html, item.author,
                    item.url, item.score, item.comment_count, posted,
                    int(msg_id) if msg_id.isdigit() else None,
                    item.source, time.time(), item.external_id,
                ),
            )
            self._conn.commit()
        return is_new

    def upsert_many(self, items) -> tuple[int, int]:
        """批量写入，返回 (新增, 总数)。"""
        new = total = 0
        for it in items:
            total += 1
            if self.upsert(it):
                new += 1
        return new, total

    # ---------------- 回填进度（断点续跑）----------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            self._conn.commit()

    @property
    def backfill_cursor(self) -> int | None:
        """回填游标：已回填到的最小消息 ID（再往前翻从这里继续）。"""
        v = self.get_meta("backfill_min_msg")
        return int(v) if v.isdigit() else None

    @backfill_cursor.setter
    def backfill_cursor(self, msg_id: int) -> None:
        self.set_meta("backfill_min_msg", str(msg_id))

    # ---------------- 查询/统计 ----------------
    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def recent(self, n: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT topic_id,title,author,score,comment_count,url "
                "FROM documents ORDER BY tg_msg_id DESC LIMIT ?", (n,),
            ).fetchall()
        cols = ["topic_id", "title", "author", "score", "comment_count", "url"]
        return [dict(zip(cols, r)) for r in rows]

    def min_msg_id(self) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(tg_msg_id) FROM documents WHERE tg_msg_id IS NOT NULL"
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    # ---------------- 采集边界表 frontier（全站调度）----------------
    def frontier_add(self, topic_ids) -> int:
        """把 topic_id 批量登记进 frontier（已存在则跳过）。返回新增数。"""
        now = time.time()
        new = 0
        with self._lock:
            for tid in topic_ids:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO frontier (topic_id,status,attempts,"
                    "updated_at,discovered_at) VALUES (?,?,?,?,?)",
                    (str(tid), "pending", 0, now, now),
                )
                new += cur.rowcount
            self._conn.commit()
        return new

    def frontier_claim(self, limit: int, status: str = "pending") -> list[str]:
        """取出一批待爬 topic_id（不做行锁，单机足够；分布式可换 Redis）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT topic_id FROM frontier WHERE status=? "
                "ORDER BY discovered_at LIMIT ?", (status, limit),
            ).fetchall()
        return [r[0] for r in rows]

    def frontier_mark(self, topic_id: str, status: str, bump_attempt: bool = False) -> None:
        with self._lock:
            if bump_attempt:
                self._conn.execute(
                    "UPDATE frontier SET status=?, attempts=attempts+1, updated_at=? "
                    "WHERE topic_id=?", (status, time.time(), str(topic_id)),
                )
            else:
                self._conn.execute(
                    "UPDATE frontier SET status=?, updated_at=? WHERE topic_id=?",
                    (status, time.time(), str(topic_id)),
                )
            self._conn.commit()

    def frontier_attempts(self, topic_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM frontier WHERE topic_id=?", (str(topic_id),)
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def frontier_stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM frontier GROUP BY status"
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def upsert_detail(self, topic_id: str, *, body: str | None = None,
                      category: str | None = None, category_id: int | None = None,
                      reply_count: int | None = None) -> None:
        """详情采集回写：更新正文/分类/楼层，并标记 detail_fetched=1。

        只更新传入的非 None 字段（COALESCE 保留原值），供两级采集的第二级用。
        """
        with self._lock:
            self._conn.execute(
                """UPDATE documents SET
                     body=COALESCE(?, body),
                     category=COALESCE(?, category),
                     category_id=COALESCE(?, category_id),
                     reply_count=COALESCE(?, reply_count),
                     detail_fetched=1,
                     fetched_at=?
                   WHERE topic_id=?""",
                (body, category, category_id, reply_count, time.time(), str(topic_id)),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
