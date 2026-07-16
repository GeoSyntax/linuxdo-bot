"""文本向量化。三档实现，按可用性自动降级：

    1. LocalEmbedder  : sentence-transformers 本地模型（bge-small-zh 等），
                        离线、免费、中文效果好 —— 契合"本地部署 + AI"目标。
    2. ApiEmbedder    : OpenAI 兼容 embedding API，效果最好但需 key + 联网。
    3. TfidfEmbedder  : 纯 numpy 的 TF-IDF + 字符/词混合特征，零额外依赖，
                        保证在没装模型、没联网时 RAG 仍能跑（回退兜底）。

统一接口：
    embed(texts: list[str]) -> np.ndarray  形状 (n, dim)，行已 L2 归一化
    dim: int
所有向量都归一化后返回，检索侧用点积即为余弦相似度。
"""
from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class Embedder(ABC):
    name: str = "base"
    model_name: str = "base"      # 具体模型标识（写入向量索引，便于区分/失配检测）
    dim: int = 0

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def needs_fit(self) -> bool:
        """是否需要先在语料上 fit（仅 TF-IDF 回退需要）。"""
        return False


class LocalEmbedder(Embedder):
    """sentence-transformers 本地模型。默认 bge-small-zh-v1.5（中文小模型）。"""

    name = "local"

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        from sentence_transformers import SentenceTransformer  # 延迟导入
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.dim = self.model.get_sentence_embedding_dimension()
        logger.info("本地 embedder 就绪：%s (dim=%d)", model_name, self.dim)

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float32)


class ApiEmbedder(Embedder):
    """OpenAI 兼容 embedding API。"""

    name = "api"

    def __init__(self, base_url: str, api_key: str,
                 model: str = "text-embedding-3-small") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.model_name = model
        self.dim = 1536  # text-embedding-3-small 默认维度

    def embed(self, texts: list[str]) -> np.ndarray:
        import requests
        resp = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        mat = np.asarray([d["embedding"] for d in data], dtype=np.float32)
        self.dim = mat.shape[1]
        return _l2_normalize(mat)


class TfidfEmbedder(Embedder):
    """零依赖回退：中文按 2-gram 字符 + 英文按词，构建 TF-IDF 向量。

    需要先 fit(语料) 建立词表与 idf；未见词忽略。维度=词表大小（上限截断）。
    这不是语义向量，但能在无模型/无网络时提供可用的关键词级检索兜底。
    """

    name = "tfidf"

    def __init__(self, max_features: int = 4096) -> None:
        self.max_features = max_features
        self.model_name = "tfidf"
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray | None = None
        self.dim = 0

    def needs_fit(self) -> bool:
        return self.idf is None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = text.lower()
        toks: list[str] = []
        # 英文/数字词
        toks += re.findall(r"[a-z0-9]+", text)
        # 中文 2-gram
        han = re.findall(r"[一-鿿]", text)
        toks += ["".join(pair) for pair in zip(han, han[1:])]
        return toks

    def fit(self, texts: list[str]) -> "TfidfEmbedder":
        df: dict[str, int] = {}
        for t in texts:
            for tok in set(self._tokenize(t)):
                df[tok] = df.get(tok, 0) + 1
        # 取最高频的 max_features 个词
        top = sorted(df.items(), key=lambda kv: kv[1], reverse=True)[: self.max_features]
        self.vocab = {tok: i for i, (tok, _) in enumerate(top)}
        n = max(1, len(texts))
        idf = np.ones(len(self.vocab), dtype=np.float32)
        for tok, i in self.vocab.items():
            idf[i] = math.log((1 + n) / (1 + df[tok])) + 1.0
        self.idf = idf
        self.dim = len(self.vocab)
        self.model_name = f"tfidf-{self.dim}"
        logger.info("TF-IDF embedder 就绪：dim=%d（回退模式）", self.dim)
        return self

    def needs_fit(self) -> bool:
        return self.idf is None

    def embed(self, texts: list[str]) -> np.ndarray:
        if self.idf is None or self.dim == 0:
            # 未 fit：返回零向量（检索将退化为无结果，调用方需先 fit）
            return np.zeros((len(texts), max(1, self.dim)), dtype=np.float32)
        mat = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            toks = self._tokenize(t)
            if not toks:
                continue
            counts: dict[int, int] = {}
            for tok in toks:
                j = self.vocab.get(tok)
                if j is not None:
                    counts[j] = counts.get(j, 0) + 1
            for j, c in counts.items():
                mat[r, j] = (c / len(toks)) * self.idf[j]
        return _l2_normalize(mat)


def get_embedder(config) -> Embedder:
    """按配置构造 embedder，不可用则降级。

    config.rag.embed_provider: local | api | tfidf(默认回退)
    """
    rag = getattr(config, "rag", None)
    provider = getattr(rag, "embed_provider", "tfidf") if rag else "tfidf"

    if provider == "local":
        try:
            return LocalEmbedder(getattr(rag, "embed_model", "BAAI/bge-small-zh-v1.5"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("本地 embedder 不可用（%s），降级 TF-IDF", exc)
            return TfidfEmbedder()
    if provider == "api":
        try:
            key = rag.embed_api.get("api_key", "")
            if not key:
                raise ValueError("缺少 embed api_key")
            return ApiEmbedder(
                base_url=rag.embed_api.get("base_url", "https://api.openai.com/v1"),
                api_key=key,
                model=rag.embed_api.get("model", "text-embedding-3-small"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("API embedder 不可用（%s），降级 TF-IDF", exc)
            return TfidfEmbedder()
    return TfidfEmbedder()
