"""RAG 问答引擎：检索 → 组织上下文 → LLM 综合 → 带引用的答案。

复用 zhihu_crawler.ai.providers 的 LLM provider（ollama/openai/rule 三档）。
无 LLM 时（rule 回退）直接给出"最相关主题 + 原帖链接"列表 —— 这本身就是
比论坛原生搜索更好用的语义检索结果，仍有实用价值。

答案**始终带原帖引用链接**：既有用，也把流量导回 linux.do（合规）。
"""
from __future__ import annotations

import html
import logging

from zhihu_crawler.ai.providers import OllamaProvider, OpenAIProvider, RuleProvider

from .retriever import Retriever

logger = logging.getLogger(__name__)

_SYSTEM = """你是 linux.do 社区的问答助手。用户问一个问题，我会给你若干条社区相关主题（标题+摘要+链接）。
请基于这些主题**综合**出简洁有用的中文回答，帮用户快速找到解决方向。要求：
1. 只依据给出的主题内容作答，不要编造；信息不足就直说"社区里没找到直接答案"。
2. 回答末尾**必须**列出引用的主题链接（用户可点进原帖看详情）。
3. 简洁，突出可操作的解决方法。"""


def _build_llm(config):
    """按 RagConfig 构造 LLM provider，不可用降级 rule。"""
    rag = config.rag
    p = rag.llm_provider
    if p == "ollama":
        prov = OllamaProvider(rag.ollama.get("host", "http://127.0.0.1:11434"),
                              rag.ollama.get("model", "qwen2.5:7b"))
    elif p == "openai":
        prov = OpenAIProvider(rag.openai.get("base_url", "https://api.openai.com/v1"),
                              rag.openai.get("api_key", ""),
                              rag.openai.get("model", "gpt-4o-mini"))
    else:
        return RuleProvider()
    if not prov.available():
        logger.warning("RAG LLM provider '%s' 不可用，降级 rule", prov.name)
        return RuleProvider()
    return prov


class RagEngine:
    def __init__(self, retriever: Retriever, config) -> None:
        self.retriever = retriever
        self.config = config
        self.llm = _build_llm(config)
        self.top_k = config.rag.top_k

    def ask(self, question: str) -> str:
        """回答用户问题，返回 HTML 文本（供 Telegram parse_mode=HTML）。"""
        hits = self.retriever.search(question, top_k=self.top_k)
        if not hits:
            return ("社区语料里还没有相关内容（可能索引为空）。\n"
                    "管理员可运行 <code>--backfill</code> 采集 + <code>--reindex</code> 建索引。")

        refs = self._format_refs(hits)

        # 无真模型 → 直接给"最相关主题"列表（已是比原生搜索好用的结果）
        if isinstance(self.llm, RuleProvider):
            return f"🔍 <b>为你找到最相关的社区主题</b>：\n\n{refs}"

        # 有模型 → 综合答案 + 引用
        context = self._build_context(hits)
        user = f"用户问题：{question}\n\n社区相关主题：\n{context}\n\n请综合作答并在末尾列出引用链接。"
        try:
            answer = self.llm.chat(_SYSTEM, user).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 生成失败（%s），回退主题列表", exc)
            return f"🔍 <b>相关社区主题</b>：\n\n{refs}"

        return f"🤖 <b>综合回答</b>\n\n{html.escape(answer)}\n\n📚 <b>参考主题</b>\n{refs}"

    @staticmethod
    def _build_context(hits: list[dict]) -> str:
        lines = []
        for i, h in enumerate(hits, 1):
            body = (h.get("body") or "")[:300]
            lines.append(f"[{i}] 标题：{h['title']}\n    摘要：{body}\n    链接：{h['url']}")
        return "\n".join(lines)

    @staticmethod
    def _format_refs(hits: list[dict]) -> str:
        out = []
        for h in hits:
            title = html.escape(h["title"][:60])
            out.append(
                f'• <a href="{html.escape(h["url"])}">{title}</a>'
                f'（💬{h.get("comment_count", 0)} 相似度{h.get("sim", 0):.2f}）'
            )
        return "\n".join(out)
