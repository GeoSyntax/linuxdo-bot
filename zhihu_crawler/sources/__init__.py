"""多源采集适配器。

每个源实现统一的 Source 接口（fetch → 产出 Item），让上层的合规内核、
去重、AI 清洗、存储保持源无关。这正是 JD 第一条"多渠道公开数据采集"的落地。

内置源（均为官方 API / robots 允许，合规无争议）：
    - HackerNewsSource : Hacker News 官方 Firebase API
    - ArxivSource      : arXiv 官方 Atom API（遵守其 3s/请求 的条款限速）
"""
from .base import Item, Source
from .hackernews import HackerNewsSource
from .arxiv import ArxivSource
from .linuxdo import LinuxDoSource
from .tgchannel import TgChannelSource

REGISTRY: dict[str, type[Source]] = {
    "hackernews": HackerNewsSource,
    "arxiv": ArxivSource,
    "linuxdo": LinuxDoSource,
    "tgchannel": TgChannelSource,
}

__all__ = [
    "Item", "Source", "HackerNewsSource", "ArxivSource",
    "LinuxDoSource", "TgChannelSource", "REGISTRY",
]
