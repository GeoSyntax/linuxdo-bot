"""多 IP 轮换全站采集：用 Clash 节点切换分散负载。

每轮用一个出口 IP（Clash 节点）采一批，热过盾后连采，采完切下一个 IP。
目的：分散 IP 风控压力，避免单 IP 冷却问题。跑完自动回退到 rule 模式。

用法（后台）：
    python -m linuxdo_bot._clash_crawl --target 2000 --batch-per-ip 20

日志输出到 stdout，用 nohup/tee 重定向到文件方便查进度。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("clash_crawl")


def _build_ip_pool():
    """从 Clash 拿到当前所有节点，跑 distinct_nodes 测出唯一 IP 池。"""
    import requests as _req
    from zhihu_crawler.distributed.clash_controller import ClashController
    cc = ClashController("http://127.0.0.1:9097", "ghy051225")
    # 采集期间必须用 global 模式，否则 Clash rule 会按域名分流、不走节点出口
    _req.patch("http://127.0.0.1:9097/configs",
               headers={"Authorization": "Bearer ghy051225"},
               json={"mode": "global"}, timeout=5)
    logger.info("Clash 已切 global 模式")
    # 排除非代理节点
    all_nodes = cc.node_names()
    banned = {"DIRECT", "REJECT", "🚀 Proxy", "REJECT-DROP", "PASS", "COMPATIBLE"}
    candidates = [n for n in all_nodes if n not in banned and "-v6" not in n]
    logger.info("候选节点 %d 个，测出口 IP…", len(candidates))
    pool = cc.distinct_nodes(candidates, max_nodes=8, settle=2.5)
    logger.info("IP 池：%d 个唯一出口", len(pool))
    for p in pool:
        logger.info("  %s  →  %s", p["node"], p["ip"])
    return cc, pool


def _crawl_batch(corpus, pool, cc, batch_size: int) -> dict:
    """用一个 IP 采一批主题，返回统计。"""
    from zhihu_crawler.sources.linuxdo import LinuxDoSource
    from zhihu_crawler.sources.browser_fetcher import BrowserFetcher
    from zhihu_crawler.compliance import TokenBucket

    claimed = corpus.frontier_claim(batch_size)
    if not claimed:
        return {"processed": 0, "ok": 0, "failed": 0, "gone": 0}

    # 选一个健康 IP，切 Clash 节点，启动带该代理的 BrowserFetcher
    bucket = TokenBucket(rate=1.0, capacity=1)   # 1 req/s per IP
    proxy_url = f"http://127.0.0.1:{cc.proxy_port()}"
    fetcher = BrowserFetcher(bucket=bucket, headless=True, proxy=proxy_url)
    source = LinuxDoSource(None, fetcher=fetcher)

    ok = failed = gone = 0
    from zhihu_crawler.sources.base import Item
    for tid in claimed:
        try:
            detail = source.fetch_topic_full(tid)
            if detail and detail.get("_gone"):
                corpus.frontier_mark(tid, "gone"); gone += 1; continue
            if not detail or not detail.get("title"):
                raise ValueError("空详情")
            corpus.upsert(Item(
                source="clash_pool", external_id=tid, title=detail["title"],
                author=detail.get("author", ""),
                content_html=detail.get("body_html", ""),
                url=f"https://linux.do/t/topic/{tid}",
                score=int(detail.get("views", 0) or 0),
                comment_count=int(detail.get("reply_count", 0) or 0),
            ))
            corpus.upsert_detail(tid, body=detail.get("body_html", ""),
                                 category_id=detail.get("category_id"),
                                 reply_count=detail.get("reply_count"))
            corpus.frontier_mark(tid, "detail_done")
            ok += 1
        except Exception as exc:
            logger.warning("主题 %s 失败: %s", tid, exc)
            corpus.frontier_mark(tid, "pending", bump_attempt=True)
            failed += 1

    fetcher.close()
    return {"processed": len(claimed), "ok": ok, "failed": failed, "gone": gone}


def main() -> None:
    ap = argparse.ArgumentParser(description="多 IP 轮换全站采集（Clash，长时间后台运行）")
    ap.add_argument("--target", type=int, default=2000, help="目标采集总数（跨所有 IP）")
    ap.add_argument("--batch-per-ip", type=int, default=20, help="每个 IP 一批采多少（避免单 IP 过热）")
    ap.add_argument("--rest", type=float, default=5.0, help="切 IP 间歇（秒）")
    args = ap.parse_args()

    from linuxdo_bot.corpus import Corpus
    import requests as _req

    corpus = Corpus("data/linuxdo_bot.db")
    start_done = corpus.frontier_stats().get("detail_done", 0)
    pending = corpus.frontier_stats().get("pending", 0)
    logger.info("起始：语料库 %d 篇，frontier pending %d，目标 + %d",
                corpus.count(), pending, args.target)

    # 如果 frontier 为空，先用已有的 sitemap_recent 数据
    if pending == 0:
        logger.warning("frontier 无 pending，先枚举 sitemap_recent")
        from linuxdo_bot.sitemap import SitemapEnumerator
        from zhihu_crawler.client import ZhihuClient
        from zhihu_crawler.config import Config as CC
        from zhihu_crawler.sources.linuxdo import LinuxDoSource as LDO
        with ZhihuClient(CC()) as cl:
            src = LDO(cl)
            try:
                enum = SitemapEnumerator(src._fetcher)
                subs = enum.list_submaps()
                recent = [s for s in subs if "recent" in s]
                for sm in recent[:1]:
                    ids = enum.topic_ids_in(sm)
                    n = corpus.frontier_add(ids)
                    logger.info("枚举 %s：新增 %d pending", sm, n)
            finally:
                src.close()
        if corpus.frontier_stats().get("pending", 0) == 0:
            logger.error("枚举后仍无 pending，退出"); corpus.close(); return

    # 构建 IP 池
    cc, pool = _build_ip_pool()
    if not pool:
        logger.error("无可用出口 IP"); _restore(cc); corpus.close(); return

    t0 = time.time()
    collected = 0
    rounds = 0
    empty_streak = 0

    while collected < args.target:
        pending_now = corpus.frontier_stats().get("pending", 0)
        if pending_now == 0:
            logger.info("frontier pending 为 0，退出")
            break

        # 轮换：按 round 选节点，均匀分配
        ip_idx = rounds % len(pool)
        chosen = pool[ip_idx]
        # 切节点
        cc.select(chosen["node"], selector="GLOBAL")
        time.sleep(2.0)  # 等切换生效

        logger.info("[轮%d] 切 IP %s (节点 %s)，采 %d 篇",
                    rounds + 1, chosen["ip"], chosen["node"], args.batch_per_ip)

        st = _crawl_batch(corpus, pool, cc, args.batch_per_ip)
        collected += st["ok"]
        elapsed = time.time() - t0
        rate = collected / elapsed * 3600 if elapsed > 0 else 0
        fr = corpus.frontier_stats()
        logger.info("[轮%d] +ok%d +fail%d +gone%d | 本次累计 %d/%d | 语料库 %d | "
                    "pending %d | %.0f篇/时 | 耗时 %.1f分",
                    rounds + 1, st["ok"], st["failed"], st["gone"],
                    collected, args.target, corpus.count(),
                    fr.get("pending", 0), rate, elapsed / 60)

        if st["processed"] == 0:
            empty_streak += 1
            if empty_streak >= 2:
                logger.info("frontier 持续无任务，退出")
                break
        else:
            empty_streak = 0

        rounds += 1
        time.sleep(args.rest)

    # 恢复 Clash 到 rule 模式
    _restore(cc)
    total = corpus.count()
    elapsed = time.time() - t0
    logger.info("采集结束：本次 + %d 篇，语料库共 %d 篇，"
                "耗时 %.1f 分钟，共 %d 轮", collected, total, elapsed / 60, rounds)
    corpus.close()


def _restore(cc):
    try:
        import requests
        requests.patch("http://127.0.0.1:9097/configs",
                       headers={"Authorization": "Bearer ghy051225"},
                       json={"mode": "rule"}, timeout=5)
        logger.info("Clash 已恢复 rule 模式")
    except Exception:
        logger.warning("Clash 恢复 rule 模式失败，请手动恢复")


if __name__ == "__main__":
    main()
