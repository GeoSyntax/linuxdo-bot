"""代理池 + 代理采集客户端测试（全程无真实网络）。"""
import time

import pytest

from zhihu_crawler.distributed.proxy_pool import ProxyPool, ProxyStat


def test_stat_health_prefers_success_and_low_latency():
    fast_good = ProxyStat("p1", ok=9, fail=1, total_latency=0.9)   # 90%,~0.1s
    slow_good = ProxyStat("p2", ok=9, fail=1, total_latency=45.0)  # 90%,~5s
    bad = ProxyStat("p3", ok=1, fail=9, total_latency=1.0)         # 10%
    # 成功率相同时，低时延健康分更高
    assert fast_good.health() > slow_good.health()
    # 成功率高的比成功率低的健康分高
    assert fast_good.health() > bad.health()


def test_new_proxy_gets_optimistic_score():
    st = ProxyStat("p")
    # 无历史时给中性乐观分，保证新代理有机会被调度
    assert st.success_rate == 0.8


def test_acquire_returns_a_proxy():
    pool = ProxyPool(["http://a", "http://b", "http://c"])
    got = pool.acquire()
    assert got in {"http://a", "http://b", "http://c"}
    assert pool.size() == 3


def test_cooldown_after_consecutive_failures():
    pool = ProxyPool(["http://a"], cooldown_base=10.0, fail_threshold=3)
    for _ in range(3):
        pool.report("http://a", ok=False)
    # 连续 3 次失败 → 进入冷却 → 不可用
    assert pool.available_count() == 0
    assert pool.acquire() is None


def test_success_resets_consecutive_fail():
    pool = ProxyPool(["http://a"], fail_threshold=3)
    pool.report("http://a", ok=False)
    pool.report("http://a", ok=False)
    pool.report("http://a", ok=True, latency=0.1)   # 成功清零连败计数
    pool.report("http://a", ok=False)
    # 只连败 1 次（<阈值），仍可用
    assert pool.available_count() == 1


def test_banned_proxy_isolated():
    pool = ProxyPool(["http://a", "http://b"])
    pool.report("http://a", ok=False, banned=True)
    assert pool.available_count() == 1
    # 反复取都不会取到被封的 a
    for _ in range(20):
        assert pool.acquire() == "http://b"


def test_revive_banned():
    pool = ProxyPool(["http://a"])
    pool.report("http://a", ok=False, banned=True)
    assert pool.available_count() == 0
    assert pool.revive_banned() == 1
    assert pool.available_count() == 1


def test_snapshot_masks_credentials():
    pool = ProxyPool(["http://user:secret@host:8080"])
    snap = pool.snapshot()
    assert len(snap) == 1
    # 快照不泄露账号密码
    assert "secret" not in snap[0]["url"]
    assert "***" in snap[0]["url"]


def test_all_proxies_in_cooldown_returns_none():
    pool = ProxyPool(["http://a", "http://b"], cooldown_base=10.0, fail_threshold=1)
    pool.report("http://a", ok=False)
    pool.report("http://b", ok=False)
    assert pool.acquire() is None


# ---------------- ProxyFetcher（假池 + 假 session，无网络）----------------

class FakePool:
    def __init__(self, proxy="http://p"):
        self._proxy = proxy
        self.reports = []

    def acquire(self):
        return self._proxy

    def report(self, url, *, ok, latency=0.0, banned=False):
        self.reports.append({"url": url, "ok": ok, "banned": banned})


class FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_fetcher_reports_ok_on_200(monkeypatch):
    from zhihu_crawler.distributed.proxy_fetcher import ProxyFetcher
    pool = FakePool()
    f = ProxyFetcher(pool)
    monkeypatch.setattr(f._session, "get", lambda *a, **k: FakeResp(200))
    resp = f.get("http://example.com")
    assert resp.status_code == 200
    assert pool.reports[-1]["ok"] is True
    assert pool.reports[-1]["banned"] is False


def test_fetcher_marks_ban_on_403(monkeypatch):
    from zhihu_crawler.distributed.proxy_fetcher import ProxyFetcher
    pool = FakePool()
    f = ProxyFetcher(pool, max_retries=1)
    monkeypatch.setattr(f._session, "get", lambda *a, **k: FakeResp(403))
    resp = f.get("http://example.com")
    assert resp is None                          # 全部重试被封 → None
    assert pool.reports[-1]["banned"] is True


def test_fetcher_retries_then_none_when_pool_empty():
    from zhihu_crawler.distributed.proxy_fetcher import ProxyFetcher

    class EmptyPool:
        def acquire(self):
            return None

        def report(self, *a, **k):
            pass

    f = ProxyFetcher(EmptyPool())
    assert f.get("http://example.com") is None


def test_fetcher_exception_reports_failure(monkeypatch):
    from zhihu_crawler.distributed.proxy_fetcher import ProxyFetcher
    pool = FakePool()
    f = ProxyFetcher(pool, max_retries=2)

    def boom(*a, **k):
        raise ConnectionError("proxy down")

    monkeypatch.setattr(f._session, "get", boom)
    resp = f.get("http://example.com")
    assert resp is None
    # 两次都异常，两次都回报失败
    assert len(pool.reports) == 2
    assert all(r["ok"] is False for r in pool.reports)
