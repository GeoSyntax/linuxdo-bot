"""多源合规采集入口（真实可跑、合法无争议）。

对接官方 API / robots 允许的公开源，跑通完整链路：
    采集(合规客户端) → 去重(布隆) → 校验 → AI 清洗 → 入库

用法：
    python -m zhihu_crawler.run_multi --source hackernews --query top --limit 8
    python -m zhihu_crawler.run_multi --source arxiv --query cs.AI --limit 5
    python -m zhihu_crawler.run_multi --source hackernews,arxiv --limit 5   # 多源
"""
from __future__ import annotations

import argparse
import logging

from .ai import ContentCleaner
from .client import ZhihuClient
from .config import get_config
from .distributed import BloomFilter
from .sources import REGISTRY
from .storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("zhihu.multi")


def main() -> None:
    ap = argparse.ArgumentParser(description="多源合规采集")
    ap.add_argument("--source", default="hackernews",
                    help="源，逗号分隔：" + " / ".join(REGISTRY))
    ap.add_argument("--query", default="", help="查询词（HN: top/new/best；arXiv: cs.AI 等）")
    ap.add_argument("--limit", type=int, default=8, help="每源采集条数")
    ap.add_argument("--no-ai", action="store_true", help="跳过 AI 清洗")
    args = ap.parse_args()

    config = get_config()
    storage = Storage(config)
    bloom = BloomFilter(capacity=1_000_000, error_rate=0.01)
    cleaner = None if args.no_ai else ContentCleaner(config)

    stats = {"fetched": 0, "deduped": 0, "cleaned": 0, "saved": 0}
    with ZhihuClient(config) as client:
        for name in [s.strip() for s in args.source.split(",") if s.strip()]:
            src_cls = REGISTRY.get(name)
            if not src_cls:
                logger.warning("未知源 %s，跳过（可选：%s）", name, list(REGISTRY))
                continue
            logger.info("=== 采集源: %s ===", name)
            source = src_cls(client)
            batch = []
            for item in source.fetch(args.query, args.limit):
                stats["fetched"] += 1
                if bloom.add(item.fingerprint):
                    continue  # 去重命中
                stats["deduped"] += 1
                batch.append(item)

            if cleaner:
                for it in batch:
                    cleaner.clean_item(it)
                    stats["cleaned"] += 1

            stats["saved"] += storage.save_items(batch)
            # 浏览器型源需释放资源
            if hasattr(source, "close"):
                source.close()

    logger.info(
        "完成：采集 %d → 去重后 %d → 清洗 %d → 入库 %d（items 表累计 %d）",
        stats["fetched"], stats["deduped"], stats["cleaned"],
        stats["saved"], storage.count("items"),
    )
    storage.close()


if __name__ == "__main__":
    main()
