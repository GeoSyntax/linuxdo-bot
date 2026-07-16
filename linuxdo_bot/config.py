"""机器人配置：环境变量优先（本地部署友好），带合理默认。

敏感项（TG token）只从环境变量 / .env 读，不写进仓库。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载（不引第三方依赖，本地部署零负担）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


@dataclass
class RagConfig:
    """RAG 配置。embed_provider: local | api | tfidf(默认回退)；
    llm_provider: ollama | openai | rule(默认回退)。"""
    embed_provider: str = "tfidf"
    embed_model: str = "BAAI/bge-small-zh-v1.5"
    embed_api: dict = field(default_factory=dict)   # {base_url, api_key, model}
    llm_provider: str = "rule"
    ollama: dict = field(default_factory=dict)       # {host, model}
    openai: dict = field(default_factory=dict)       # {base_url, api_key, model}
    top_k: int = 5


@dataclass
class BotConfig:
    tg_token: str = ""
    tg_api_base: str = "https://api.telegram.org"
    # 监控
    categories: list[str] = field(default_factory=lambda: ["latest"])  # latest 或分类 slug
    poll_interval: int = 300           # 采集轮询间隔（秒）
    fetch_limit: int = 30              # 每轮每列表取多少主题
    fetch_detail: bool = False         # 是否二跳取正文（更准但更慢）
    # 存储
    db_path: str = "data/linuxdo_bot.db"
    # 限速（合规）
    requests_per_second: float = 0.33  # 约 3s/请求
    headless: bool = True
    # RAG
    rag: "RagConfig" = field(default_factory=RagConfig)

    @classmethod
    def load(cls) -> "BotConfig":
        _load_dotenv(_ROOT / ".env")
        env = os.environ.get
        cats = env("LINUXDO_CATEGORIES", "latest")
        rag = RagConfig(
            embed_provider=env("RAG_EMBED_PROVIDER", "tfidf"),
            embed_model=env("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
            embed_api={
                "base_url": env("RAG_EMBED_API_BASE", "https://api.openai.com/v1"),
                "api_key": env("RAG_EMBED_API_KEY", "") or env("OPENAI_API_KEY", ""),
                "model": env("RAG_EMBED_API_MODEL", "text-embedding-3-small"),
            },
            llm_provider=env("RAG_LLM_PROVIDER", "rule"),
            ollama={"host": env("OLLAMA_HOST", "http://127.0.0.1:11434"),
                    "model": env("OLLAMA_MODEL", "qwen2.5:7b")},
            openai={"base_url": env("OPENAI_API_BASE", "https://api.openai.com/v1"),
                    "api_key": env("OPENAI_API_KEY", ""),
                    "model": env("OPENAI_MODEL", "gpt-4o-mini")},
            top_k=int(env("RAG_TOP_K", "5")),
        )
        return cls(
            tg_token=env("TG_BOT_TOKEN", ""),
            tg_api_base=env("TG_API_BASE", "https://api.telegram.org"),
            categories=[c.strip() for c in cats.split(",") if c.strip()],
            poll_interval=int(env("POLL_INTERVAL", "300")),
            fetch_limit=int(env("FETCH_LIMIT", "30")),
            fetch_detail=env("FETCH_DETAIL", "false").lower() == "true",
            db_path=env("DB_PATH", "data/linuxdo_bot.db"),
            requests_per_second=float(env("REQUESTS_PER_SECOND", "0.33")),
            headless=env("HEADLESS", "true").lower() == "true",
            rag=rag,
        )

    @property
    def db_full_path(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else _ROOT / p
