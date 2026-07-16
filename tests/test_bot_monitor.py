"""监控分发逻辑测试：用假源/假通知，验证匹配→去重→推送。"""
import pytest

from linuxdo_bot.config import BotConfig
from linuxdo_bot.monitor import Monitor
from linuxdo_bot.store import Store
from zhihu_crawler.sources.base import Item


class FakeSource:
    def __init__(self, items):
        self._items = items

    def fetch(self, query, limit):
        return iter(self._items[:limit])

    def fetch_topic_detail(self, tid):
        return ""

    def close(self):
        pass


def _items():
    return [
        Item(source="linuxdo", external_id="1", title="Python 异步编程",
             author="a", url="https://linux.do/t/topic/1", comment_count=10, score=100),
        Item(source="linuxdo", external_id="2", title="Rust 入门",
             author="b", url="https://linux.do/t/topic/2", comment_count=5, score=50),
    ]


@pytest.fixture
def setup():
    store = Store(":memory:")
    sent = []
    cfg = BotConfig(categories=["latest"], fetch_limit=10, fetch_detail=False)
    mon = Monitor(cfg, store, notifier=lambda cid, text: sent.append((cid, text)))
    # 绕过真实采集：直接调 _handle_item
    yield mon, store, sent
    store.close()


def _handle_all(mon, store, src):
    subs = store.all_subscriptions()
    usubs = store.all_user_subscriptions()
    for it in src.fetch("latest", 10):
        mon._handle_item(it, subs, usubs)


def test_match_pushes(setup):
    mon, store, sent = setup
    store.add_subscription("u1", "python")
    _handle_all(mon, store, FakeSource(_items()))
    assert len(sent) == 1
    assert sent[0][0] == "u1"
    assert "Python 异步编程" in sent[0][1]


def test_no_match_no_push(setup):
    mon, store, sent = setup
    store.add_subscription("u1", "java")
    _handle_all(mon, store, FakeSource(_items()))
    assert sent == []


def test_push_dedup_across_polls(setup):
    mon, store, sent = setup
    store.add_subscription("u1", "rust")
    # 两轮采集同样的 items，应只推一次
    for _ in range(2):
        _handle_all(mon, store, FakeSource(_items()))
    assert len(sent) == 1


def test_multiple_users(setup):
    mon, store, sent = setup
    store.add_subscription("u1", "python")
    store.add_subscription("u2", "rust")
    _handle_all(mon, store, FakeSource(_items()))
    chats = {c for c, _ in sent}
    assert chats == {"u1", "u2"}


def test_user_subscription_matches_author(setup):
    mon, store, sent = setup
    store.add_user_subscription("u1", "a")   # 关注作者 a
    _handle_all(mon, store, FakeSource(_items()))
    # _items()[0] 作者是 "a"
    assert len(sent) == 1
    assert "@a" in sent[0][1]
