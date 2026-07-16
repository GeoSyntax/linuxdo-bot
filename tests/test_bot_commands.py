"""命令路由 + 监控匹配逻辑测试。"""
import pytest

from linuxdo_bot.commands import CommandRouter
from linuxdo_bot.store import Store


@pytest.fixture
def router():
    s = Store(":memory:")
    yield CommandRouter(s), s
    s.close()


def test_help(router):
    r, _ = router
    assert "监控机器人" in r.handle("u1", "/start")
    assert "监控机器人" in r.handle("u1", "/help")


def test_subscribe_user(router):
    r, _ = router
    assert "已关注用户" in r.handle("u1", "/subscribe_user neo")
    assert "neo" in r.handle("u1", "/list")
    assert "已取消关注" in r.handle("u1", "/unsubscribe_user neo")


def test_sub_and_list(router):
    r, _ = router
    assert "已订阅" in r.handle("u1", "/sub python")
    out = r.handle("u1", "/list")
    assert "python" in out


def test_sub_requires_arg(router):
    r, _ = router
    assert "用法" in r.handle("u1", "/sub")


def test_duplicate_sub_message(router):
    r, _ = router
    r.handle("u1", "/sub python")
    assert "已订阅过" in r.handle("u1", "/sub python")


def test_unsub(router):
    r, _ = router
    r.handle("u1", "/sub python")
    assert "已取消" in r.handle("u1", "/unsub python")
    assert "未找到" in r.handle("u1", "/unsub python")


def test_unknown_command(router):
    r, _ = router
    assert "未知命令" in r.handle("u1", "/foobar")


def test_non_command(router):
    r, _ = router
    assert "/help" in r.handle("u1", "hello")


def test_latest_with_callback(router):
    r, _ = router
    from zhihu_crawler.sources.base import Item
    r.fetch_latest = lambda n: [
        Item(source="linuxdo", external_id="1", title="Python 教程",
             url="https://linux.do/t/topic/1", comment_count=5),
    ]
    r.handle("u1", "/sub python")
    out = r.handle("u1", "/latest 3")
    assert "Python 教程" in out
    assert "🔔" in out  # 命中订阅应标记
