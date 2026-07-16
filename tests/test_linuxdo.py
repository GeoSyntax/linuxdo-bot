"""linux.do 源测试：Discourse JSON 解析（mock 浏览器抓取器，不启真浏览器）。"""
import json

from zhihu_crawler.sources.linuxdo import LinuxDoSource


class FakeFetcher:
    """假抓取器：直接返回预置文本，替代 Playwright。"""

    def __init__(self, text):
        self.text = text
        self.urls = []

    def get_text(self, url):
        self.urls.append(url)
        return self.text

    def close(self):
        pass


LATEST_JSON = json.dumps({
    "users": [
        {"id": 1, "username": "neo"},
        {"id": 2, "username": "alice"},
    ],
    "topic_list": {"topics": [
        {
            "id": 1001, "title": "欢迎来到 linux.do",
            "posts_count": 100, "views": 5000,
            "posters": [
                {"user_id": 1, "description": "Original Poster"},
                {"user_id": 2, "description": "Frequent Poster"},
            ],
            "tags": ["公告", {"name": "置顶"}],  # 混合 str/dict，考验容错
        },
        {
            "id": 1002, "title": "如何优雅地写爬虫",
            "posts_count": 20, "views": 800,
            "posters": [{"user_id": 2, "description": "帖子作者"}],  # 非英文标记
            "tags": [],
        },
    ]},
})


def _source():
    # client 传 None：LinuxDoSource 用注入的 fetcher，不碰 client
    return LinuxDoSource(client=None, fetcher=FakeFetcher(LATEST_JSON))


def test_linuxdo_parse_basic():
    src = _source()
    items = list(src.fetch("latest", limit=5))
    assert len(items) == 2
    a = items[0]
    assert a.source == "linuxdo"
    assert a.external_id == "1001"
    assert a.title == "欢迎来到 linux.do"
    assert a.score == 5000          # views 映射到 score
    assert a.comment_count == 100   # posts_count 映射到评论数


def test_linuxdo_author_from_original_poster():
    items = list(_source().fetch("latest", limit=5))
    assert items[0].author == "neo"       # Original Poster 标记命中


def test_linuxdo_author_fallback_first_poster():
    """非英文标记时回退到第一个 poster。"""
    items = list(_source().fetch("latest", limit=5))
    assert items[1].author == "alice"     # 回退 posters[0]


def test_linuxdo_tags_mixed_types():
    """tags 含 str 和 dict 都能正确转字符串，不报错。"""
    items = list(_source().fetch("latest", limit=5))
    assert items[0].tags == "公告,置顶"


def test_linuxdo_respects_limit():
    items = list(_source().fetch("latest", limit=1))
    assert len(items) == 1


def test_linuxdo_category_url():
    """分类查询走 /c/{slug}.json。"""
    f = FakeFetcher(LATEST_JSON)
    src = LinuxDoSource(client=None, fetcher=f)
    list(src.fetch("develop", limit=1))
    assert f.urls[0].endswith("/c/develop.json")


def test_linuxdo_bad_json_no_crash():
    src = LinuxDoSource(client=None, fetcher=FakeFetcher("<html>Just a moment</html>"))
    assert list(src.fetch("latest", limit=5)) == []
