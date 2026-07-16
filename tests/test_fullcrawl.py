"""全站采集引擎测试：frontier 任务表、sitemap 解析、调度器（用假 fetcher）。"""
import pytest

from linuxdo_bot.corpus import Corpus
from linuxdo_bot.sitemap import SitemapEnumerator


# ---------------- frontier 任务表 ----------------
@pytest.fixture
def corpus():
    c = Corpus(":memory:")
    yield c
    c.close()


def test_frontier_add_idempotent(corpus):
    assert corpus.frontier_add(["1", "2", "3"]) == 3
    assert corpus.frontier_add(["2", "3", "4"]) == 1   # 只有 4 是新的
    assert corpus.frontier_stats() == {"pending": 4}


def test_frontier_claim_and_mark(corpus):
    corpus.frontier_add(["10", "11", "12"])
    claimed = corpus.frontier_claim(2)
    assert len(claimed) == 2
    corpus.frontier_mark(claimed[0], "detail_done")
    stats = corpus.frontier_stats()
    assert stats.get("detail_done") == 1
    assert stats.get("pending") == 2


def test_frontier_claim_only_pending(corpus):
    corpus.frontier_add(["1", "2"])
    corpus.frontier_mark("1", "detail_done")
    claimed = corpus.frontier_claim(10)   # 只应拿到 pending 的 "2"
    assert claimed == ["2"]


def test_frontier_attempts(corpus):
    corpus.frontier_add(["1"])
    assert corpus.frontier_attempts("1") == 0
    corpus.frontier_mark("1", "pending", bump_attempt=True)
    assert corpus.frontier_attempts("1") == 1


def test_upsert_detail_updates_fields(corpus):
    from zhihu_crawler.sources.base import Item
    corpus.upsert(Item(source="s", external_id="1", title="T", author="a",
                       url="u", score=1, comment_count=2))
    corpus.upsert_detail("1", body="正文", category_id=4, reply_count=99)
    row = corpus._conn.execute(
        "SELECT body,category_id,reply_count,detail_fetched FROM documents WHERE topic_id='1'"
    ).fetchone()
    assert row == ("正文", 4, 99, 1)


# ---------------- sitemap 解析 ----------------
class FakeFetcher:
    """按 URL 返回预设 XML 文本。"""
    def __init__(self, mapping):
        self._m = mapping

    def get_text(self, url):
        return self._m[url]


_INDEX_XML = """<?xml version="1.0"?>
<sitemapindex>
  <sitemap><loc>https://linux.do/sitemap_1.xml</loc></sitemap>
  <sitemap><loc>https://linux.do/sitemap_2.xml</loc></sitemap>
</sitemapindex>"""

_SUB1_XML = """<?xml version="1.0"?>
<urlset>
  <url><loc>https://linux.do/t/topic/1</loc></url>
  <url><loc>https://linux.do/t/some-slug/22</loc></url>
  <url><loc>https://linux.do/t/topic/1</loc></url>
</urlset>"""


def test_sitemap_list_submaps():
    f = FakeFetcher({"https://linux.do/sitemap.xml": _INDEX_XML})
    enum = SitemapEnumerator(f)
    subs = enum.list_submaps()
    assert subs == ["https://linux.do/sitemap_1.xml", "https://linux.do/sitemap_2.xml"]


def test_sitemap_topic_ids_dedup():
    f = FakeFetcher({"https://linux.do/sitemap_1.xml": _SUB1_XML})
    enum = SitemapEnumerator(f)
    ids = enum.topic_ids_in("https://linux.do/sitemap_1.xml")
    assert ids == ["1", "22"]     # 去重、含 slug 形式也能抽出


def test_sitemap_enumerate_all_into_frontier(corpus):
    f = FakeFetcher({
        "https://linux.do/sitemap.xml": _INDEX_XML,
        "https://linux.do/sitemap_1.xml": _SUB1_XML,
        "https://linux.do/sitemap_2.xml": _SUB1_XML.replace("/1<", "/99<"),
    })
    enum = SitemapEnumerator(f)
    res = enum.enumerate_all(corpus)
    assert res["submaps"] == 2
    assert corpus.frontier_stats()["pending"] >= 2


def test_sitemap_enumerate_resumable(corpus):
    """已完成的子图不重复处理（进度记 meta）。"""
    f = FakeFetcher({
        "https://linux.do/sitemap.xml": _INDEX_XML,
        "https://linux.do/sitemap_1.xml": _SUB1_XML,
        "https://linux.do/sitemap_2.xml": _SUB1_XML,
    })
    enum = SitemapEnumerator(f)
    enum.enumerate_all(corpus, max_submaps=1)
    done_first = corpus.get_meta("sitemap_done_submaps")
    assert "sitemap_1.xml" in done_first
    # 再跑全部：sitemap_1 应被跳过，不报错
    res = enum.enumerate_all(corpus)
    assert res["submaps"] == 2
