"""RAG 子系统：把语料库文档向量化，做语义检索 + LLM 综合问答。

分层（都可降级，保证任何环境可跑）：
    embedder.py  文本 → 向量。三档：本地 sentence-transformers / OpenAI API / TF-IDF 回退
    index.py     向量存储与相似度检索（纯 numpy，零额外依赖）
    retriever.py 语料库 + embedder + 索引：建索引 / 检索
    engine.py    检索 + 组织上下文 + 调 LLM provider 生成带引用的答案
"""
from .embedder import get_embedder, Embedder
from .retriever import Retriever
from .engine import RagEngine

__all__ = ["get_embedder", "Embedder", "Retriever", "RagEngine"]
