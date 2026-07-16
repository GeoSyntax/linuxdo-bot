"""向量索引 + 检索。

存储：向量以 float32 blob 存进 SQLite（embeddings 表），与语料库同库。
检索：一次性载入所有向量到内存矩阵，用点积（向量已归一化=余弦相似度）
      做 top-k。规模在数万条以内时暴力检索足够快、零额外依赖。

    升级路径：数据量到百万级可换 sqlite-vec / FAISS，检索接口不变。

分块策略：每篇主题 = 标题 + 正文摘要，拼成一个 chunk（论坛帖摘要本就短，
不必再切段）。chunk 与 topic 一一对应，检索结果直接映射回原帖链接。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    topic_id  TEXT PRIMARY KEY,
    dim       INTEGER NOT NULL,
    vec       BLOB NOT NULL,
    model     TEXT,
    updated_at REAL
);
"""


def _doc_text(title: str, body: str) -> str:
    body = (body or "").strip()
    return f"{title}\n{body}" if body else title


class VectorIndex:
    """SQLite 向量存储 + 内存暴力检索。"""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # 内存缓存
        self._ids: list[str] = []
        self._mat: np.ndarray | None = None
        self._dirty = True

    def upsert_vectors(self, rows: list[tuple[str, np.ndarray]], model: str) -> int:
        """写入 (topic_id, vec) 列表。vec 需已归一化。返回写入条数。"""
        if not rows:
            return 0
        with self._lock:
            for topic_id, vec in rows:
                v = np.asarray(vec, dtype=np.float32)
                self._conn.execute(
                    "INSERT INTO embeddings (topic_id,dim,vec,model,updated_at) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT(topic_id) DO UPDATE SET "
                    "dim=excluded.dim, vec=excluded.vec, model=excluded.model, "
                    "updated_at=excluded.updated_at",
                    (topic_id, v.shape[0], v.tobytes(), model, time.time()),
                )
            self._conn.commit()
        self._dirty = True
        return len(rows)

    def _load(self) -> None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT topic_id,dim,vec FROM embeddings"
            ).fetchall()
        if not rows:
            self._ids, self._mat = [], None
            self._dirty = False
            return
        dim = rows[0][1]
        ids: list[str] = []
        mat = np.empty((len(rows), dim), dtype=np.float32)
        k = 0
        for topic_id, d, blob in rows:
            if d != dim:
                continue  # 维度不一致（换过模型）跳过，避免崩
            ids.append(topic_id)
            mat[k] = np.frombuffer(blob, dtype=np.float32)
            k += 1
        self._ids = ids
        self._mat = mat[:k]
        self._dirty = False
        logger.info("向量索引载入内存：%d 条 (dim=%d)", k, dim)

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> list[tuple[str, float]]:
        """返回 [(topic_id, score)]，按相似度降序。"""
        if self._dirty or self._mat is None:
            self._load()
        if self._mat is None or len(self._ids) == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        if q.shape[0] != self._mat.shape[1]:
            logger.warning("查询向量维度 %d 与索引 %d 不符", q.shape[0], self._mat.shape[1])
            return []
        scores = self._mat @ q                       # 已归一化 → 余弦相似度
        k = min(top_k, len(scores))
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self._ids[i], float(scores[i])) for i in idx]

    def clear(self) -> None:
        """清空所有向量（换 embedder/维度变化时全量重建用）。"""
        with self._lock:
            self._conn.execute("DELETE FROM embeddings")
            self._conn.commit()
        self._ids, self._mat = [], None
        self._dirty = True

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

    def existing_ids(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT topic_id FROM embeddings").fetchall()
        return {r[0] for r in rows}
