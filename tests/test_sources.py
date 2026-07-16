"""多源适配器测试：Item 模型 + HN/arXiv 解析（mock 响应，不打网络）。"""
from types import SimpleNamespace

from zhihu_crawler.sources.base import Item
from zhihu_crawler.sources.hackernews import HackerNewsSource
from zhihu_crawler.sources.arxiv import ArxivSource


# ---- Item 模型 ----
def test_item_fingerprint_stable():
    a = Item(source="hackernews", external_id="123", title="X")
    b = Item(source="hackernews", external_id="123", title="Y different")
    assert a.fingerprint == b.fingerprint  # 指纹只认 source+id


def test_item_fingerprint_differs_by_source():
    a = Item(source="hackernews", external_id="1", title="X")
    b = Item(source="arxiv", external_id="1", title="X")
    assert a.fingerprint != b.fingerprint


def test_item_validation():
    assert not Item(source="s", external_id="", title="t").is_valid()   # 缺 id
    assert not Item(source="s", external_id="1", title="").is_valid()   # 缺标题
    assert Item(source="s", external_id="1", title="ok").is_valid()


# ---- 假客户端：按 URL 返回 mock 响应 ----
class FakeResp:
    def __init__(self, payload=None, text=""):
        self._p = payload
        self.text = text

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, routes):
        self.routes = routes  # dict: url 子串 -> FakeResp

    def fetch(self, url, signed=False, respect_robots=True):
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(f"未 mock 的 url: {url}")


# ---- HN 解析 ----
def test_hackernews_parse():
    routes = {
        "topstories.json": FakeResp(payload=[111, 222]),
        "item/111.json": FakeResp(payload={
            "type": "story", "id": 111, "title": "Show HN: Foo",
            "by": "alice", "score": 250, "descendants": 30,
            "url": "https://foo.com",
        }),
        "item/222.json": FakeResp(payload={
            "type": "story", "id": 222, "title": "Ask HN: Bar",
            "by": "bob", "score": 90, "descendants": 12, "text": "<p>body</p>",
        }),
    }
    src = HackerNewsSource(FakeClient(routes))
    items = list(src.fetch("top", limit=2))
    assert len(items) == 2
    assert items[0].source == "hackernews"
    assert items[0].title == "Show HN: Foo"
    assert items[0].author == "alice"
    assert items[0].score == 250
    assert items[1].content_html == "<p>body</p>"


def test_hackernews_respects_limit():
    routes = {
        "topstories.json": FakeResp(payload=list(range(1, 21))),
        **{f"item/{i}.json": FakeResp(payload={
            "type": "story", "id": i, "title": f"T{i}", "by": "u", "score": 1,
        }) for i in range(1, 21)},
    }
    src = HackerNewsSource(FakeClient(routes))
    assert len(list(src.fetch("top", limit=3))) == 3


# ---- arXiv 解析 ----
ARXIV_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>A Great Paper on
    Crawling</title>
    <summary>We study compliant crawling.</summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Roe</name></author>
    <category term="cs.AI"/>
    <category term="cs.IR"/>
  </entry>
</feed>"""


def test_arxiv_parse():
    src = ArxivSource(FakeClient({"query": FakeResp(text=ARXIV_XML)}))
    items = list(src.fetch("cs.AI", limit=5))
    assert len(items) == 1
    it = items[0]
    assert it.source == "arxiv"
    assert it.external_id == "2401.00001"
    assert "A Great Paper on Crawling" == it.title  # 空白已归一
    assert it.author == "Jane Doe, John Roe"
    assert "cs.AI" in it.tags


def test_arxiv_query_fallback():
    """非 arXiv 语义的 query（如 HN 的 'top'）应回退默认分类，不报错。"""
    captured = {}

    class CapClient(FakeClient):
        def fetch(self, url, signed=False, respect_robots=True):
            captured["url"] = url
            return FakeResp(text=ARXIV_XML)

    src = ArxivSource(CapClient({}))
    list(src.fetch("top", limit=1))
    assert "cat:cs.AI" in captured["url"]  # 回退到默认
