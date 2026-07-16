"""机器人存储层测试（内存 SQLite）。"""
import pytest

from linuxdo_bot.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_subscribe_and_list(store):
    assert store.add_subscription("u1", "python")
    assert store.add_subscription("u1", "rust")
    assert store.list_subscriptions("u1") == ["python", "rust"]


def test_duplicate_subscription(store):
    assert store.add_subscription("u1", "python")
    assert store.add_subscription("u1", "python") is False   # 重复


def test_empty_keyword_rejected(store):
    assert store.add_subscription("u1", "   ") is False


def test_unsubscribe(store):
    store.add_subscription("u1", "python")
    assert store.remove_subscription("u1", "python")
    assert store.list_subscriptions("u1") == []
    assert store.remove_subscription("u1", "python") is False  # 已无


def test_all_subscriptions_grouped(store):
    store.add_subscription("u1", "python")
    store.add_subscription("u1", "go")
    store.add_subscription("u2", "rust")
    allsubs = store.all_subscriptions()
    assert set(allsubs["u1"]) == {"python", "go"}
    assert allsubs["u2"] == ["rust"]


def test_seen_dedup(store):
    assert store.is_seen("t1") is False
    store.mark_seen("t1")
    assert store.is_seen("t1") is True
    store.mark_seen("t1")  # 幂等


def test_pushed_dedup(store):
    assert store.already_pushed("u1", "t1") is False
    store.mark_pushed("u1", "t1")
    assert store.already_pushed("u1", "t1") is True
    assert store.already_pushed("u2", "t1") is False  # 按用户区分
