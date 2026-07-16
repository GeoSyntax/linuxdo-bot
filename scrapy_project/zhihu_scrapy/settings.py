"""Scrapy-Redis 分布式配置。

核心：把默认调度器/去重换成 scrapy-redis 版本，多节点共享 Redis 队列，
实现「一处 push 起始 URL，多机并行消费」的分布式采集。

合规基线（与单机版一致，不因分布式而放松）：
    - 遵守 robots.txt
    - AutoThrottle 自适应限速 + 保守并发
    - 下载延迟兜底
"""

BOT_NAME = "zhihu_scrapy"
SPIDER_MODULES = ["zhihu_scrapy.spiders"]
NEWSPIDER_MODULE = "zhihu_scrapy.spiders"

# ---------------- 合规基线 ----------------
ROBOTSTXT_OBEY = True                 # 遵守 robots
CONCURRENT_REQUESTS = 4               # 保守并发
DOWNLOAD_DELAY = 3.0                  # 每请求间隔兜底
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True           # 自适应限速：按服务器响应动态调节
AUTOTHROTTLE_START_DELAY = 3.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

# ---------------- Scrapy-Redis 分布式核心 ----------------
# 用 redis 的调度器：请求队列存 redis，多节点共享
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
# 用 redis 的去重：集群级 URL 去重（可换成 RFPDupeFilter / 布隆版）
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
# 持久化队列：爬虫停止后不清空，支持断点续爬
SCHEDULER_PERSIST = True
# 队列调度策略：优先级队列
SCHEDULER_QUEUE_CLASS = "scrapy_redis.queue.PriorityQueue"
REDIS_URL = "redis://127.0.0.1:6379/0"

# ---------------- 管道：清洗 + 存储 ----------------
ITEM_PIPELINES = {
    "zhihu_scrapy.pipelines.ValidationPipeline": 200,
    "zhihu_scrapy.pipelines.AICleanPipeline": 300,
    # scrapy-redis 也可把 item 存到 redis 供另一进程消费：
    # "scrapy_redis.pipelines.RedisPipeline": 400,
    "zhihu_scrapy.pipelines.StoragePipeline": 500,
}

# 请求头
DEFAULT_REQUEST_HEADERS = {
    "Accept": "application/json, text/html",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
LOG_LEVEL = "INFO"
