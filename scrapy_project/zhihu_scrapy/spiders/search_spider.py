"""分布式搜索爬虫（RedisSpider）。

start_urls 不写死在代码里，而是从 Redis 的一个列表 key 里取——
这样多个节点跑同一个 spider，共同消费一份任务队列，实现分布式。

启动方式：
    # 节点 1..N（每台机器都执行）
    scrapy crawl zhihu_search

    # 在另一个终端往队列推种子（一次即可，所有节点共享）
    redis-cli lpush zhihu_search:start_urls \
        "https://www.zhihu.com/api/v4/search_v3?t=general&q=python"
"""
import json

try:
    from scrapy_redis.spiders import RedisSpider
    _BASE = RedisSpider
except ImportError:  # 未装 scrapy-redis 时降级为普通 Spider，保证 import 不炸
    import scrapy
    _BASE = scrapy.Spider

from zhihu_scrapy.items import AnswerItem


class SearchSpider(_BASE):
    name = "zhihu_search"
    # RedisSpider 从这个 key 读起始 URL
    redis_key = "zhihu_search:start_urls"

    def parse(self, response):
        """解析搜索 API 的 JSON 响应。"""
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("响应非 JSON: %s", response.url)
            return

        for entry in payload.get("data", []):
            obj = entry.get("object") or entry
            if obj.get("type") not in (None, "answer", "article"):
                continue
            author = obj.get("author") or {}
            question = obj.get("question") or {}
            item = AnswerItem(
                answer_id=str(obj.get("id", "")),
                question_title=question.get("name", "") if isinstance(question, dict) else obj.get("title", ""),
                author=author.get("name", "") if isinstance(author, dict) else "",
                content_html=obj.get("content", "") or obj.get("excerpt", ""),
                voteup_count=int(obj.get("voteup_count", 0) or 0),
                comment_count=int(obj.get("comment_count", 0) or 0),
                url=obj.get("url", ""),
                content_markdown="",
                sentiment="",
                is_cleaned=False,
                crawled_at=0.0,
            )
            yield item

        # 翻页：合规地跟进 next（受 AutoThrottle + DOWNLOAD_DELAY 约束）
        paging = payload.get("paging") or {}
        if not paging.get("is_end") and paging.get("next"):
            yield response.follow(paging["next"], callback=self.parse)
