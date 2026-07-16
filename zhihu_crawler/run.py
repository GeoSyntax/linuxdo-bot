"""单机入口：合规、小规模地跑一次采集 -> 清洗 -> 存储全链路。

用法：
    python -m zhihu_crawler.run --keyword python --limit 5

说明：
    - 默认遵守 robots + 限速。若知乎接口需签名/登录态而当前环境无 d_c0，
      采集会失败（合规地失败，不绕过）。此时可先用离线 demo 展示能力：
          python -m zhihu_crawler.demos.demo_signature
          python -m zhihu_crawler.demos.demo_ai_clean
"""
from __future__ import annotations

import argparse
import logging
from urllib.parse import quote

from .ai import ContentCleaner
from .client import ComplianceError, ZhihuClient
from .config import get_config
from .distributed import BloomFilter
from .parser import parse_search_api
from .storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("zhihu.run")


def main() -> None:
    ap = argparse.ArgumentParser(description="知乎合规采集（单机版）")
    ap.add_argument("--keyword", required=True, help="搜索关键词")
    ap.add_argument("--limit", type=int, default=5, help="最多采集条数")
    ap.add_argument("--d-c0", default="", help="cookie d_c0（可选，用于签名）")
    ap.add_argument("--no-ai", action="store_true", help="跳过 AI 清洗")
    ap.add_argument(
        "--base-url", default="",
        help="覆盖采集域名。指向本地沙箱(http://127.0.0.1:8901)或授权测试环境时，"
             "可端到端跑通全链路；留空则用 config 里的生产域名（受 robots 限制）",
    )
    args = ap.parse_args()

    config = get_config()
    if args.base_url:
        config.crawler["base_url"] = args.base_url.rstrip("/")
    storage = Storage(config)
    bloom = BloomFilter(capacity=100_000, error_rate=0.01)
    cleaner = None if args.no_ai else ContentCleaner(config)

    url = (
        f"{config.crawler.get('base_url')}/api/v4/search_v3"
        f"?t=general&q={quote(args.keyword)}&correction=1"
        f"&offset=0&limit={args.limit}"
    )

    logger.info("开始采集: %s", url)
    try:
        with ZhihuClient(config, d_c0=args.d_c0) as client:
            resp = client.fetch(url, signed=bool(args.d_c0))
            answers = parse_search_api(resp.text)
    except ComplianceError as e:
        logger.error("合规拦截: %s", e)
        return
    except Exception as e:
        logger.error("采集失败（合规地失败，未绕过反爬）: %s", e)
        logger.info("可先运行离线 demo 展示能力：python -m zhihu_crawler.demos.demo_ai_clean")
        return

    # 去重
    fresh = [a for a in answers if not bloom.add(a.fingerprint)]
    logger.info("采集 %d 条，去重后 %d 条", len(answers), len(fresh))

    # AI 清洗
    if cleaner:
        fresh = cleaner.clean_batch(fresh)

    # 校验 + 存储
    saved = storage.save_many(fresh)
    logger.info("入库 %d 条，库内累计 %d 条", saved, storage.count())
    storage.close()


if __name__ == "__main__":
    main()
