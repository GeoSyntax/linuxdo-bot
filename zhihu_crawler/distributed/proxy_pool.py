"""分布式采集的代理池管理器。

分布式爬虫要真正并行，单 IP 是硬瓶颈（目标站按 IP 限速/风控）。多出口 IP
才能横向扩展——代理池负责管理这批出口 IP：健康检查、加权轮换、失败冷却、
封禁隔离，让上层采集器"拿一个当前最健康的代理"而不必关心底层细节。

⚠️ 合规边界（重要）：
    用代理池绕过目标站的 IP 频率限制，本质是"规避网站主动设置的防护"。
    本模块是**架构能力实现**（对应 JD 的分布式爬虫加分项），默认对接**中立/
    允许的端点**做验证；是否用于某个具体站点，取决于你是否获得该站授权。
    个人作品集建议：坚持单 IP 合规限速，代理池仅作分布式架构展示。

设计要点（面试可讲）：
    - 加权轮换：按每个代理的实时健康分（成功率+时延）选取，不是简单轮询；
    - 失败冷却：连续失败进入冷却期（指数退避），到期自动恢复，避免雪崩；
    - 封禁隔离：识别到被封（如 403/挑战）的代理临时踢出，不拖累整体；
    - 线程/进程安全：单机用锁；跨机可把状态放 Redis（见 RedisProxyPool 注释）。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProxyStat:
    """单个代理的运行时统计与健康状态。"""

    url: str
    ok: int = 0
    fail: int = 0
    total_latency: float = 0.0
    # 冷却：cooldown_until 之前不参与调度
    cooldown_until: float = 0.0
    consecutive_fail: int = 0
    banned: bool = False

    @property
    def attempts(self) -> int:
        return self.ok + self.fail

    @property
    def success_rate(self) -> float:
        # 无历史时给中性乐观分 0.8，让新代理有机会被试用
        return self.ok / self.attempts if self.attempts else 0.8

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.ok if self.ok else 1.0

    def health(self) -> float:
        """健康分 ∈ (0,1]：成功率为主，低时延加成。用于加权选取。"""
        # 时延惩罚：1s 基准，越慢分越低，限制在 [0.3, 1]
        lat_factor = max(0.3, min(1.0, 1.0 / (1.0 + self.avg_latency)))
        return self.success_rate * lat_factor

    def available(self, now: float) -> bool:
        return (not self.banned) and now >= self.cooldown_until


class ProxyPool:
    """线程安全的代理池：加权选取 + 失败冷却 + 封禁隔离。"""

    def __init__(
        self,
        proxies: list[str],
        cooldown_base: float = 5.0,
        cooldown_max: float = 300.0,
        fail_threshold: int = 3,
    ) -> None:
        """
        proxies       : 代理 URL 列表，如 ["http://user:pass@host:port", ...]
        cooldown_base : 冷却基数（秒），连续失败按指数增长
        cooldown_max  : 冷却上限（秒）
        fail_threshold: 连续失败达到此数进入冷却
        """
        self._stats: dict[str, ProxyStat] = {u: ProxyStat(u) for u in proxies}
        self._cooldown_base = cooldown_base
        self._cooldown_max = cooldown_max
        self._fail_threshold = fail_threshold
        self._lock = threading.Lock()
        logger.info("代理池初始化：%d 个代理", len(self._stats))

    def size(self) -> int:
        return len(self._stats)

    def available_count(self) -> int:
        now = time.time()
        with self._lock:
            return sum(1 for s in self._stats.values() if s.available(now))

    def acquire(self) -> str | None:
        """按健康分加权随机选一个当前可用代理；无可用返回 None。

        加权随机（而非取最高分）：既偏向健康代理，又保留探索，避免所有流量
        砸向同一个代理把它打挂。
        """
        now = time.time()
        with self._lock:
            usable = [s for s in self._stats.values() if s.available(now)]
            if not usable:
                return None
            weights = [s.health() for s in usable]
            chosen = random.choices(usable, weights=weights, k=1)[0]
            return chosen.url

    def report(self, url: str, *, ok: bool, latency: float = 0.0,
               banned: bool = False) -> None:
        """回报一次使用结果，更新健康状态与冷却。"""
        with self._lock:
            st = self._stats.get(url)
            if st is None:
                return
            if banned:
                st.banned = True
                st.fail += 1
                st.consecutive_fail += 1
                logger.warning("代理被标记封禁，隔离：%s", url)
                return
            if ok:
                st.ok += 1
                st.total_latency += latency
                st.consecutive_fail = 0
                st.cooldown_until = 0.0
            else:
                st.fail += 1
                st.consecutive_fail += 1
                if st.consecutive_fail >= self._fail_threshold:
                    # 指数退避冷却：base * 2^(超出阈值的次数)，封顶
                    over = st.consecutive_fail - self._fail_threshold
                    delay = min(self._cooldown_base * (2 ** over), self._cooldown_max)
                    st.cooldown_until = time.time() + delay
                    logger.warning("代理连续失败 %d 次，冷却 %.0fs：%s",
                                   st.consecutive_fail, delay, url)

    def revive_banned(self) -> int:
        """手动恢复所有被封代理（如换了 IP 段/等待足够久后）。返回恢复数。"""
        with self._lock:
            n = 0
            for st in self._stats.values():
                if st.banned:
                    st.banned = False
                    st.consecutive_fail = 0
                    st.cooldown_until = 0.0
                    n += 1
        return n

    def snapshot(self) -> list[dict]:
        """导出各代理状态，便于监控/调试。"""
        now = time.time()
        with self._lock:
            out = []
            for st in self._stats.values():
                out.append({
                    "url": _mask(st.url),
                    "ok": st.ok,
                    "fail": st.fail,
                    "success_rate": round(st.success_rate, 3),
                    "avg_latency": round(st.avg_latency, 3),
                    "health": round(st.health(), 3),
                    "available": st.available(now),
                    "banned": st.banned,
                    "cooldown_in": max(0.0, round(st.cooldown_until - now, 1)),
                })
            return out


def _mask(url: str) -> str:
    """隐去代理 URL 里的账号密码，日志/快照不泄露凭据。"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _creds, _, host = rest.partition("@")
    return f"{scheme}://***@{host}" if scheme else f"***@{host}"


# ─────────────────────────────────────────────────────────────
# 跨机扩展说明（面试可讲）：
#   单机 ProxyPool 用内存 + 锁。要多台采集机共享同一批代理的健康状态：
#   把 _stats 换成 Redis 哈希（每个代理一个 key，字段 ok/fail/cooldown_until），
#   acquire 用 Lua 脚本原子地"读全部可用 → 加权选取 → 返回"，report 用
#   HINCRBY 更新计数。这样多机看到一致的代理健康视图，坏代理全局冷却。
#   与 RedisBloomDedup（去重）+ Redis frontier（任务队列）组合，即完整的
#   分布式采集集群。
# ─────────────────────────────────────────────────────────────
