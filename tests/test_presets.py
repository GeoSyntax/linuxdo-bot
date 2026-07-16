"""快捷预置 + inline 回调测试。"""
from linuxdo_bot.commands import CommandRouter
from linuxdo_bot.presets import keyword_buttons, charity_buttons, QUICK_KEYWORDS
from linuxdo_bot.store import Store


def test_keyword_buttons_shape():
    rows = keyword_buttons()
    # 每个按钮 callback_data 形如 sub:xxx，且覆盖所有预置词
    flat = [b for row in rows for b in row]
    assert len(flat) == len(QUICK_KEYWORDS)
    assert all(b["callback_data"].startswith("sub:") for b in flat)
    assert all(len(row) <= 3 for row in rows)  # 每行≤3


def test_charity_buttons_callback_prefix():
    for row in charity_buttons():
        for b in row:
            assert b["callback_data"].startswith("subuser:")


def test_callback_subscribe_keyword():
    s = Store(":memory:")
    r = CommandRouter(s)
    note = r.handle_callback("u1", "sub:claude")
    assert "已订阅" in note
    assert "claude" in s.list_subscriptions("u1")
    # 重复点击
    assert "已订阅过" in r.handle_callback("u1", "sub:claude")
    s.close()


def test_callback_subscribe_user():
    s = Store(":memory:")
    r = CommandRouter(s)
    note = r.handle_callback("u1", "subuser:neo")
    assert "已关注" in note
    assert "neo" in s.list_user_subscriptions("u1")
    s.close()


def test_quick_command_returns_marker():
    s = Store(":memory:")
    r = CommandRouter(s)
    assert r.handle("u1", "/quick") == "QUICK"
    s.close()


def test_unknown_callback():
    s = Store(":memory:")
    r = CommandRouter(s)
    assert "未知" in r.handle_callback("u1", "bogus:x")
    s.close()
