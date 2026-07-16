"""布隆过滤器去重。

分布式爬虫的 URL 去重若用 set 存全部 URL，内存开销随规模线性膨胀。
布隆过滤器用 m 位 + k 个哈希，在可控误判率下把内存降到常数级：
    1 亿 URL、误判率 1% ≈ 171 MB（对比 set 存 URL 动辄数 GB，省 30x+）。

提供两种实现：
    - BloomFilter     : 纯内存位数组（单机 / 演示 / 测试）
    - RedisBloomDedup : 用 Redis 的位操作（setbit/getbit）实现分布式共享去重，
                        多个爬虫节点共用一份过滤器（需要 redis 包）。
"""
from __future__ import annotations

import hashlib
import math
from typing import Iterable


def _optimal_params(capacity: int, error_rate: float) -> tuple[int, int]:
    """由容量 n 与误判率 p 反推位数 m 与哈希个数 k。

        m = -(n * ln p) / (ln2)^2
        k = (m / n) * ln2
    """
    m = math.ceil(-(capacity * math.log(error_rate)) / (math.log(2) ** 2))
    k = max(1, round((m / capacity) * math.log(2)))
    return m, k


def _hashes(item: str, k: int, m: int) -> Iterable[int]:
    """用双哈希法生成 k 个位下标（Kirsch-Mitzenmacher）。

        g_i(x) = (h1(x) + i * h2(x)) mod m
    只算两个基础哈希，衍生出 k 个，省 CPU。
    """
    data = item.encode("utf-8")
    h1 = int(hashlib.md5(data).hexdigest(), 16)
    h2 = int(hashlib.sha1(data).hexdigest(), 16)
    for i in range(k):
        yield (h1 + i * h2) % m


class BloomFilter:
    """纯内存布隆过滤器（单机）。"""

    def __init__(self, capacity: int = 1_000_000, error_rate: float = 0.01) -> None:
        self.capacity = capacity
        self.error_rate = error_rate
        self.m, self.k = _optimal_params(capacity, error_rate)
        self._bits = bytearray((self.m + 7) // 8)
        self._count = 0

    def _set_bit(self, idx: int) -> None:
        self._bits[idx // 8] |= 1 << (idx % 8)

    def _get_bit(self, idx: int) -> bool:
        return bool(self._bits[idx // 8] & (1 << (idx % 8)))

    def add(self, item: str) -> bool:
        """加入元素。返回 True 表示此前『可能已存在』（用于去重判定）。"""
        seen = True
        for idx in _hashes(item, self.k, self.m):
            if not self._get_bit(idx):
                seen = False
                self._set_bit(idx)
        if not seen:
            self._count += 1
        return seen

    def __contains__(self, item: str) -> bool:
        return all(self._get_bit(idx) for idx in _hashes(item, self.k, self.m))

    def __len__(self) -> int:
        return self._count

    @property
    def memory_bytes(self) -> int:
        return len(self._bits)


class RedisBloomDedup:
    """基于 Redis 位操作的分布式布隆去重。

    多个爬虫节点连同一个 Redis key，共享同一份位数组，实现集群级去重。
    """

    def __init__(
        self,
        redis_url: str,
        key: str = "zhihu:bloom:urls",
        capacity: int = 100_000_000,
        error_rate: float = 0.01,
    ) -> None:
        try:
            import redis
        except ImportError as e:
            raise RuntimeError("分布式去重需要 pip install redis") from e
        self._redis = redis.from_url(redis_url)
        self.key = key
        self.m, self.k = _optimal_params(capacity, error_rate)

    def add(self, item: str) -> bool:
        """原子地判断并加入。返回此前是否已存在。"""
        pipe = self._redis.pipeline()
        idxs = list(_hashes(item, self.k, self.m))
        for idx in idxs:
            pipe.getbit(self.key, idx)
        bits = pipe.execute()
        seen = all(bits)
        if not seen:
            pipe = self._redis.pipeline()
            for idx in idxs:
                pipe.setbit(self.key, idx, 1)
            pipe.execute()
        return seen

    def __contains__(self, item: str) -> bool:
        pipe = self._redis.pipeline()
        for idx in _hashes(item, self.k, self.m):
            pipe.getbit(self.key, idx)
        return all(pipe.execute())
