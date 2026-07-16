"""分布式扩展：布隆去重（可选依赖 Redis）+ 代理池（多出口 IP 横向扩展）。"""
from .dedup import BloomFilter, RedisBloomDedup
from .proxy_pool import ProxyPool, ProxyStat
from .proxy_fetcher import ProxyFetcher

__all__ = [
    "BloomFilter", "RedisBloomDedup",
    "ProxyPool", "ProxyStat", "ProxyFetcher",
]
