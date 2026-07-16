"""RAG 子系统测试：TF-IDF embedder + 向量索引 + 检索器 + 引擎（全离线）。"""
import numpy as np
import pytest

from linuxdo_bot.config import BotConfig
from linuxdo_bot.corpus import Corpus
from linuxdo_bot.rag.embedder import TfidfEmbedder, get_embedder
from linuxdo_bot.rag.index import VectorIndex
from linuxdo_bot.rag.retriever import Retriever
from linuxdo_bot.rag.engine import RagEngine
from zhihu_crawler.sources.base import Item


def _mk_item(tid, title, body=""):
    return Item(source="tgchannel", external_id=str(tid), title=title,
                content_html=body, url=f"https://linux.do/t/topic/{tid}",
                tags=f"tg_msg:{tid},posted:2026")


# ---------------- TF-IDF embedder ----------------
def test_tfidf_needs_fit_then_embeds():
    e = TfidfEmbedder()
    assert e.needs_fit()
    e.fit(["codex 怎么用", "grok 好用吗", "显卡 oom 解决"])
    assert not e.needs_fit()
    vecs = e.embed(["codex 用法"])
    assert vecs.shape[0] == 1
    # 归一化：范数≈1（非零向量）
    assert abs(np.linalg.norm(vecs[0]) - 1.0) < 1e-4


def test_tfidf_similar_text_higher_score():
    e = TfidfEmbedder().fit(["codex 额度 超限 怎么办", "grok 4.5 无敌", "显卡 oom"])
    q = e.embed(["codex 超限"])[0]
    d_codex = e.embed(["codex 额度 超限 怎么办"])[0]
    d_grok = e.embed(["grok 4.5 无敌"])[0]
    assert float(q @ d_codex) > float(q @ d_grok)


# ---------------- 向量索引 ----------------
def test_index_upsert_and_search():
    c = Corpus(":memory:")
    idx = VectorIndex(c._conn, c._lock)
    # 三个正交单位向量
    idx.upsert_vectors([("a", np.array([1, 0, 0], np.float32)),
                        ("b", np.array([0, 1, 0], np.float32)),
                        ("c", np.array([0, 0, 1], np.float32))], model="t")
    hits = idx.search(np.array([1, 0, 0], np.float32), top_k=2)
    assert hits[0][0] == "a"
    assert hits[0][1] > hits[1][1]
    c.close()


def test_index_clear():
    c = Corpus(":memory:")
    idx = VectorIndex(c._conn, c._lock)
    idx.upsert_vectors([("a", np.array([1.0, 0], np.float32))], model="t")
    assert idx.count() == 1
    idx.clear()
    assert idx.count() == 0
    c.close()


# ---------------- 检索器（端到端，TF-IDF）----------------
@pytest.fixture
def retriever():
    c = Corpus(":memory:")
    for it in [
        _mk_item(1, "codex5.6怎么用", "新版本 codex 使用方法"),
        _mk_item(2, "grok 4.5 无敌了", "grok 比 gpt 强"),
        _mk_item(3, "如何避免显卡 oom", "炼丹显存不足解决"),
    ]:
        c.upsert(it)
    cfg = BotConfig()  # tfidf + rule
    r = Retriever(c, TfidfEmbedder())
    r.reindex()
    yield r, cfg
    c.close()


def test_retriever_search_relevant(retriever):
    r, _ = retriever
    hits = r.search("codex 用法", top_k=3)
    assert hits
    assert hits[0]["topic_id"] == "1"       # codex 帖排第一
    assert "url" in hits[0] and hits[0]["url"].endswith("/1")


def test_retriever_oom_query(retriever):
    # TF-IDF 回退是关键词级匹配（非语义）：查询需含文档里的实际词。
    # 真实语义检索用本地/API embedder，这里验证回退档的关键词命中。
    r, _ = retriever
    hits = r.search("显卡 oom 解决", top_k=3)
    assert hits[0]["topic_id"] == "3"


# ---------------- 引擎（rule 回退：返回主题列表）----------------
def test_engine_rule_returns_refs(retriever):
    r, cfg = retriever
    eng = RagEngine(r, cfg)
    ans = eng.ask("codex 怎么用")
    assert "codex" in ans.lower()
    assert "linux.do/t/topic/1" in ans   # 带原帖引用链接


def test_engine_empty_corpus():
    c = Corpus(":memory:")
    cfg = BotConfig()
    eng = RagEngine(Retriever(c, TfidfEmbedder()), cfg)
    ans = eng.ask("任何问题")
    assert "没有" in ans or "索引" in ans   # 空语料友好提示
    c.close()


def test_get_embedder_defaults_tfidf():
    assert get_embedder(BotConfig()).name == "tfidf"


def test_search_autofits_fresh_embedder(retriever):
    """跨进程场景：新建未 fit 的 embedder 也能检索（search 内部自动 fit）。"""
    r, _ = retriever
    # 模拟新进程：换一个全新的、未 fit 的 embedder
    r.embedder = TfidfEmbedder()
    assert r.embedder.needs_fit()
    hits = r.search("codex 用法", top_k=3)
    assert hits and hits[0]["topic_id"] == "1"
