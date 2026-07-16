"""LLM Provider 抽象。

三档实现，任何环境都能跑：
    - RuleProvider   : 纯规则/正则，零依赖零联网，保证离线可运行（默认）
    - OllamaProvider : 本地 Ollama HTTP，隐私友好、零成本
    - OpenAIProvider : OpenAI 兼容 API

统一接口 chat(system, user) -> str，上层清洗逻辑与具体模型解耦。
（呼应 LangGraph/RAG 经验：provider 抽象是构建 Agent 的基础。）
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(self, system: str, user: str) -> str:
        """给定 system/user 提示，返回模型文本输出。"""
        raise NotImplementedError

    def available(self) -> bool:
        """provider 是否可用（用于自动降级）。"""
        return True


class RuleProvider(LLMProvider):
    """离线规则回退：不依赖任何模型，保证 demo 与测试可跑。

    - 清洗：剥 HTML 标签、压缩空白、按已知广告词过滤段落。
    - 情感：基于中文情感词典的朴素打分。
    这不是"真 AI"，但保证了系统在无模型环境下仍产出可用结构化结果，
    并作为 LLM 不可用时的兜底（生产级鲁棒性）。
    """

    name = "rule"

    _AD_PATTERNS = [
        r"(微信|vx|v信|QQ)\s*[:：]?\s*\w", r"加.{0,4}(微信|vx|v信|QQ)",
        r"点击.{0,6}链接", r"广告", r"推广", r"扫码",
        r"关注.{0,6}公众号", r"私信我?", r"福利.{0,6}领取", r"领取.{0,6}(教程|资料|福利)",
    ]
    _POS_WORDS = ["好", "赞", "优秀", "喜欢", "推荐", "强大", "满意", "值得", "厉害", "棒"]
    _NEG_WORDS = ["差", "垃圾", "失望", "糟糕", "讨厌", "问题", "坑", "难用", "退款", "骗"]

    def chat(self, system: str, user: str) -> str:
        # 从 user 提示里取出待处理正文（约定：正文在 ```...``` 之间或全文）
        m = re.search(r"```(.*?)```", user, re.S)
        raw = m.group(1) if m else user
        text = self._html_to_text(raw)

        # 段落级去广告
        paras = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
        kept = [p for p in paras if not self._is_ad(p)]
        markdown = "\n\n".join(kept)

        sentiment = self._sentiment(markdown)
        # 返回与 LLM 一致的 JSON 结构，便于上层统一解析
        return json.dumps(
            {"markdown": markdown, "sentiment": sentiment}, ensure_ascii=False
        )

    @staticmethod
    def _html_to_text(html_text: str) -> str:
        # 先整块删除 script/style 及其内容（否则代码会残留在正文里）
        text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", html_text,
                      flags=re.I | re.S)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p>", "\n\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)          # 去剩余标签
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _is_ad(self, para: str) -> bool:
        return any(re.search(p, para) for p in self._AD_PATTERNS)

    def _sentiment(self, text: str) -> str:
        pos = sum(text.count(w) for w in self._POS_WORDS)
        neg = sum(text.count(w) for w in self._NEG_WORDS)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        return "neutral"


class OllamaProvider(LLMProvider):
    """本地 Ollama。默认 http://127.0.0.1:11434。"""

    name = "ollama"

    def __init__(self, host: str, model: str) -> None:
        self.host = host.rstrip("/")
        self.model = model

    def available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API。"""

    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def get_provider(config) -> LLMProvider:
    """按配置构造 provider，不可用时自动降级到 RuleProvider。"""
    ai = config.ai
    provider: LLMProvider
    if ai.provider == "ollama":
        provider = OllamaProvider(
            host=ai.ollama.get("host", "http://127.0.0.1:11434"),
            model=ai.ollama.get("model", "qwen2.5:7b"),
        )
    elif ai.provider == "openai":
        provider = OpenAIProvider(
            base_url=ai.openai.get("base_url", "https://api.openai.com/v1"),
            api_key=ai.openai.get("api_key", ""),
            model=ai.openai.get("model", "gpt-4o-mini"),
        )
    else:
        return RuleProvider()

    if not provider.available():
        logger.warning("provider '%s' 不可用，降级到规则模式", provider.name)
        return RuleProvider()
    return provider
