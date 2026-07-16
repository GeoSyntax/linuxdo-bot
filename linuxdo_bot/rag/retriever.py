"""检索器：把语料库文档向量化建索引，并对查询做语义检索。

职责：
    reindex()  : 把语料库里尚未向量化的文档批量 embedding → 存入向量索引
    search()   : 查询向量化 → top-k 相似主题 → 返回带原文链接的结果

与语料库共用一个 SQLite 连接（同库、embeddings 表与 documents 表并存），
本地部署只有一个 .db 文件，最省心。
"""
from __future__ import annotations

import logging

from ..corpus import Corpus
from .embedder import Embedder
from .index import VectorIndex, _doc_text

logger = logging.getLogger(__name__)


class Retriever:
    def __init__(self, corpus: Corpus, embedder: Embedder) -> None:
        self.corpus = corpus
        self.embedder = embedder
        # 复用 corpus 的连接与锁，embeddings 表落在同一个库
        self.index = VectorIndex(corpus._conn, corpus._lock)

    def reindex(self, batch: int = 256, limit: int | None = None) -> dict:
        """把语料库中未建向量的文档补齐索引。返回统计。"""
        docs = self._all_docs()
        # TF-IDF 回退需先在全语料上 fit（建词表/idf）；本地/API 模型无需
        if self.embedder.needs_fit() and docs:
            self.embedder.fit([_doc_text(d["title"], d["body"]) for d in docs])
            # fit 后维度可能变化，已有向量作废，全量重建
            self.index.clear()

        done = self.index.existing_ids()
        pending = [d for d in docs if d["topic_id"] not in done]
        if limit:
            pending = pending[:limit]
        if not pending:
            return {"indexed": 0, "total": self.index.count()}

        indexed = 0
        for i in range(0, len(pending), batch):
            chunk = pending[i:i + batch]
            texts = [_doc_text(d["title"], d["body"]) for d in chunk]
            vecs = self.embedder.embed(texts)
            rows = [(d["topic_id"], v) for d, v in zip(chunk, vecs)]
            indexed += self.index.upsert_vectors(rows, model=self.embedder.model_name)
            logger.info("已索引 %d/%d", min(i + batch, len(pending)), len(pending))
        return {"indexed": indexed, "total": self.index.count()}

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """语义检索，返回 [{topic_id,title,url,author,score,sim,body}]。"""
        # TF-IDF 回退跨进程时（如 --reindex 与 --ask 分开跑）需按同一语料重新 fit
        # 才能得到与索引一致的维度；确定性 fit 保证跨进程维度对齐。
        if self.embedder.needs_fit():
            docs = self._all_docs()
            if docs:
                self.embedder.fit([_doc_text(d["title"], d["body"]) for d in docs])
        qvec = self.embedder.embed([query])[0]
        hits = self.index.search(qvec, top_k=top_k)
        if not hits:
            return []
        by_id = {d["topic_id"]: d for d in self._all_docs()}
        out = []
        for topic_id, sim in hits:
            d = by_id.get(topic_id)
            if not d:
                continue
            out.append({**d, "sim": round(sim, 4)})
        return out

    def _all_docs(self) -> list[dict]:
        with self.corpus._lock:
            rows = self.corpus._conn.execute(
                "SELECT topic_id,title,body,author,url,score,comment_count "
                "FROM documents"
            ).fetchall()
        cols = ["topic_id", "title", "body", "author", "url", "score", "comment_count"]
        return [dict(zip(cols, r)) for r in rows]
