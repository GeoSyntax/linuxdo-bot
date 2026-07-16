"""限速与退避重试。

- TokenBucket：令牌桶限速器，线程安全。控制平均速率与突发容量，
  保证不对目标服务器造成压力（合规内核核心）。
- retry_with_backoff：指数退避重试装饰器，应对偶发网络抖动 / 429 / 5xx。
"""
from __future__ import annotations

import functools
import logging
import random
import threading
import time
from typing import Callable, Iterable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TokenBucket:
    """经典令牌桶。

    以 rate 个令牌/秒的速度补充，桶容量为 capacity（突发上限）。
    acquire() 在没有令牌时阻塞等待，从而把请求速率平滑到设定值。
    """

    def __init__(self, rate: float, capacity: int = 1) -> None:
        if rate <= 0:
            raise ValueError("rate 必须为正")
        self.rate = rate
        self.capacity = max(1, capacity)
        self._tokens = float(self.capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def acquire(self, tokens: int = 1) -> float:
        """获取 tokens 个令牌，不足则阻塞。返回实际等待秒数。"""
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                # 需要等待的时间：差额 / 速率
                deficit = tokens - self._tokens
                sleep_for = deficit / self.rate
            time.sleep(sleep_for)
            waited += sleep_for


def retry_with_backoff(
    max_retries: int = 3,
    base: float = 2.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    jitter: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """指数退避重试装饰器。

    第 n 次失败后等待 min(base ** n, max_delay) 秒（可加随机抖动），
    避免同时重试造成的雪崩（thundering herd）。
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        break
                    delay = min(base ** attempt, max_delay)
                    if jitter:
                        delay *= 0.5 + random.random()  # 0.5x ~ 1.5x
                    logger.warning(
                        "调用失败(第%d/%d次): %s，%.1fs 后重试",
                        attempt + 1, max_retries, exc, delay,
                    )
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
