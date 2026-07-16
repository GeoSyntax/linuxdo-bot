"""限速与退避测试。"""
import time

import pytest

from zhihu_crawler.compliance.throttle import TokenBucket, retry_with_backoff


def test_token_bucket_first_acquire_no_wait():
    """桶初始满，首次取不等待。"""
    tb = TokenBucket(rate=10, capacity=1)
    assert tb.acquire() == 0.0


def test_token_bucket_rate_limits():
    """速率 5/s、容量1：连取两次，第二次约等 ~0.2s。"""
    tb = TokenBucket(rate=5, capacity=1)
    tb.acquire()
    start = time.monotonic()
    tb.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15  # 容忍调度抖动


def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    @retry_with_backoff(max_retries=3, base=1.01, max_delay=0.01, jitter=False)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_exhausts_and_raises():
    @retry_with_backoff(max_retries=2, base=1.0, max_delay=0.01, jitter=False)
    def always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        always_fail()


def test_token_bucket_rejects_bad_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate=0)
