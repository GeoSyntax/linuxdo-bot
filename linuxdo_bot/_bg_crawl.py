"""后台持续采集脚本：分批跑 crawl_details，断点续跑，直到达标或队列空。

用法：
    python -m linuxdo_bot._bg_crawl --target 2000 --batch 50 --rps 1.0

每批打印一行进度（供后台监控），中断后重跑会从 frontier pending 继续。
这是"稳定持续跑"的入口，与 --fullcrawl（一次一批）互补。
"""
from __future__ import annotations

import argparse
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from .config import BotConfig
from .corpus import Corpus
from .fullcrawl import FullCrawler


def main() -> None:
    ap = argparse.ArgumentParser(description="后台持续全站采集（断点续跑）")
    ap.add_argument("--target", type=int, default=2000, help="本次目标新增 detail_done 篇数")
    ap.add_argument("--batch", type=int, default=50, help="每批采集数")
    ap.add_argument("--rps", type=float, default=1.0, help="请求/秒（默认1.0）")
    args = ap.parse_args()

    cfg = BotConfig.load()
    cfg.requests_per_second = args.rps
    corpus = Corpus(cfg.db_full_path)
    fc = FullCrawler(cfg, corpus)

    start_done = corpus.frontier_stats().get("detail_done", 0)
    print(f"[BG] 启动：起始 detail_done={start_done}，目标 +{args.target}，"
          f"batch={args.batch}，rps={args.rps}", flush=True)

    t0 = time.time()
    collected = 0
    empty_rounds = 0
    while collected < args.target:
        st = fc.crawl_details(args.batch)
        if st["processed"] == 0:
            empty_rounds += 1
            if empty_rounds >= 2:
                print("[BG] frontier 无 pending，采集完成，退出。", flush=True)
                break
            continue
        empty_rounds = 0
        collected += st["ok"]
        fr = st["frontier"]
        elapsed = time.time() - t0
        rate = collected / elapsed if elapsed > 0 else 0
        print(f"[BG] +{st['ok']} 失败{st['failed']} 失效{st['gone']} | "
              f"本次累计{collected}/{args.target} | 语料库{st['corpus_total']} | "
              f"pending{fr.get('pending', 0)} | {rate*3600:.0f}篇/时", flush=True)

    total = corpus.count()
    print(f"[BG] 结束：本次新增 {collected} 篇，语料库共 {total} 篇，"
          f"耗时 {(time.time()-t0)/60:.1f} 分钟。", flush=True)
    corpus.close()


if __name__ == "__main__":
    main()
