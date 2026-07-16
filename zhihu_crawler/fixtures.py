"""知乎同结构的样例数据。

用于本地沙箱 / 离线端到端演示：这些 JSON 的字段结构与知乎 search_v3
API 的响应一致，让解析器、去重、AI 清洗、存储的整条流水线能真实跑通、
被测试覆盖，而无需去抓生产环境（合规 + 可复现）。

内容为构造的示例文本（含广告/灌水，用于演示 AI 清洗），非真实用户数据。
"""
from __future__ import annotations

# 一页 search_v3 响应（结构对齐知乎真实 API）
SEARCH_V3_PAGE = {
    "data": [
        {
            "object": {
                "type": "answer",
                "id": 900000001,
                "content": (
                    "<div class=\"RichText\"><p>Python 做数据采集非常成熟，"
                    "requests + lxml 起步，规模化上 Scrapy。</p>"
                    "<p>关键是把限速和去重做好，别把对方服务器打挂。</p>"
                    "<p>加我微信 vx: spam123 领全套爬虫教程福利！</p>"
                    "<script>track()</script>"
                    "<p>总体来说，Python 生态对爬虫极其友好，强烈推荐。</p></div>"
                ),
                "voteup_count": 1287,
                "comment_count": 43,
                "author": {"name": "数据小王"},
                "question": {"name": "Python 适合做爬虫吗？"},
                "url": "https://www.zhihu.com/question/19550001/answer/900000001",
            }
        },
        {
            "object": {
                "type": "answer",
                "id": 900000002,
                "content": (
                    "<div class=\"RichText\"><p>反爬的核心是提高对方识别成本，"
                    "合规前提下做限速退避、UA 轮换就够日常用了。</p>"
                    "<p>签名类接口要理解它的生成逻辑，逆向是理解而非硬刚。</p>"
                    "<p>说实话有些回答质量太差，纯灌水浪费时间。</p></div>"
                ),
                "voteup_count": 356,
                "comment_count": 12,
                "author": {"name": "反爬老兵"},
                "question": {"name": "常见反爬策略有哪些？"},
                "url": "https://www.zhihu.com/question/19550002/answer/900000002",
            }
        },
        {
            "object": {
                "type": "article",
                "id": 900000003,
                "content": (
                    "<div class=\"RichText\"><p>分布式爬虫用 Scrapy-Redis，"
                    "多节点共享队列，布隆过滤器做去重省内存。</p>"
                    "<p>断点续爬靠 Redis 持久化调度。</p></div>"
                ),
                "voteup_count": 89,
                "comment_count": 5,
                "author": {"name": "架构笔记"},
                "title": "分布式爬虫架构小结",
                "url": "https://zhuanlan.zhihu.com/p/900000003",
            }
        },
        # 故意重复一条（id 相同），用于演示去重
        {
            "object": {
                "type": "answer",
                "id": 900000001,
                "content": "<p>重复内容，应被布隆去重拦截</p>",
                "voteup_count": 1287,
                "comment_count": 43,
                "author": {"name": "数据小王"},
                "question": {"name": "Python 适合做爬虫吗？"},
                "url": "https://www.zhihu.com/question/19550001/answer/900000001",
            }
        },
    ],
    "paging": {"is_end": True, "next": ""},
}


def search_v3(keyword: str = "python", limit: int = 5) -> dict:
    """返回一页样例响应（可按 limit 截断）。"""
    page = {"data": SEARCH_V3_PAGE["data"][:limit], "paging": SEARCH_V3_PAGE["paging"]}
    return page
