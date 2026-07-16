# Scrapy-Redis 分布式采集工程

单机版核心逻辑（signature/parser/ai/storage）在 `../zhihu_crawler/`，本工程复用它们，只负责分布式调度。

## 依赖

```bash
pip install scrapy scrapy-redis redis
```

## 运行（分布式）

```bash
# 1. 启动 Redis
redis-server

# 2. 在每个节点启动 spider（可多机、多进程）
cd scrapy_project
scrapy crawl zhihu_search

# 3. 在另一终端推入起始 URL（一次即可，所有节点共享消费）
redis-cli lpush zhihu_search:start_urls \
  "https://www.zhihu.com/api/v4/search_v3?t=general&q=python&offset=0&limit=20"
```

## 合规基线（与单机版一致）

- `ROBOTSTXT_OBEY = True`
- `AutoThrottle` 自适应限速 + `DOWNLOAD_DELAY = 3s`
- `RETRY_HTTP_CODES = [429, 500, 502, 503, 504]`

## 管道顺序

`ValidationPipeline`（校验）→ `AICleanPipeline`（LLM 清洗）→ `StoragePipeline`（落库）

> 注：AI 清洗是 IO 密集，规模化时建议拆成独立消费进程（见 `../docs/architecture.md` 第 5 节）。
