"""Scrapy 管道：校验 -> AI 清洗 -> 存储。

复用单机版 zhihu_crawler 的 models / ai / storage，避免重复实现，
体现「单机与分布式共享同一套领域逻辑」的工程设计。
"""
import logging
import sys
from pathlib import Path

from itemadapter import ItemAdapter

# 让分布式工程能 import 到单机版核心模块
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zhihu_crawler.config import get_config          # noqa: E402
from zhihu_crawler.models import Answer               # noqa: E402
from zhihu_crawler.ai import ContentCleaner           # noqa: E402
from zhihu_crawler.storage import Storage             # noqa: E402

logger = logging.getLogger(__name__)


class ValidationPipeline:
    """字段校验，不合格直接丢弃。"""

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        answer = Answer(**{k: adapter.get(k) for k in adapter.keys() if k in Answer.__annotations__})
        problems = answer.validate()
        if problems:
            from scrapy.exceptions import DropItem
            raise DropItem(f"校验不通过: {problems}")
        return item


class AICleanPipeline:
    """AI 清洗：填充 markdown + sentiment。"""

    def open_spider(self, spider):
        self.cleaner = ContentCleaner(get_config())

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        source = adapter.get("content_html") or ""
        if source:
            markdown, sentiment = self.cleaner.clean_text(source)
            adapter["content_markdown"] = markdown
            adapter["sentiment"] = sentiment
            adapter["is_cleaned"] = True
        return item


class StoragePipeline:
    """落库（SQLite/MySQL）。"""

    def open_spider(self, spider):
        self.storage = Storage(get_config())

    def close_spider(self, spider):
        self.storage.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        answer = Answer(**{k: adapter.get(k) for k in adapter.keys() if k in Answer.__annotations__})
        self.storage.save(answer)
        return item
