# RAG 智能搜索设计（/ask）

> linux.do 原生搜索不好用。`/ask` 用**语义检索 + LLM 综合**帮用户快速找到社区里已有的解决方法，**答案始终带原帖引用链接**——既有用，也把流量导回 linux.do（合规，不做内容镜像替代站）。

## 1. 数据流

```
监控采集/回填 ──▶ 语料库(corpus: documents)
                      │
              reindex │ embedding
                      ▼
                向量索引(embeddings 表, SQLite blob)
                      ▲
         /ask 问题 ───┘ 检索 top-k
                      │
                      ▼
              LLM 综合(带引用) ──▶ 用户
```

- **语料沉淀**：监控循环每采到一条主题就 `corpus.upsert`；`--backfill` 从官方 TG 频道 `?before=` 往前翻做历史回填，进度记在 `meta` 表，**断点续跑**。
- **建索引**：`--reindex` 把未向量化的文档批量 embedding 存入 `embeddings` 表。
- **检索**：查询向量化 → 与索引矩阵点积（向量已 L2 归一化 = 余弦相似度）取 top-k。

## 2. 三档降级（任何环境可跑）

| 层 | 首选 | 次选 | 回退 |
|---|---|---|---|
| embedding | `local`（sentence-transformers，如 bge-small-zh，中文语义） | `api`（OpenAI 兼容 `/embeddings`） | `tfidf`（纯 numpy 的 2-gram/词 TF-IDF，零依赖） |
| 生成 | `ollama`（本地模型） | `openai`（云 API） | `rule`（不生成，直接给最相关主题列表） |

**关键点**：即使既没装模型、也没 API key、还没联网，`tfidf + rule` 组合仍能给出"最相关主题 + 原帖链接"——这本身已是比论坛原生搜索更好用的语义/关键词检索。

## 3. 向量存储选型

- 向量以 `float32` blob 存进 SQLite（与语料库同一个 `.db`，本地部署只有一个文件）。
- 检索一次性载入内存矩阵，numpy 暴力点积。**数万条内足够快、零额外依赖**。
- 升级路径：数据量到百万级可换 `sqlite-vec` / FAISS，`VectorIndex.search` 接口不变。

## 4. 跨进程一致性（一个真实的坑）

TF-IDF 的词表/idf 依赖语料。`--reindex` 与 `--ask` 是不同进程，各自新建 embedder。修法：`Retriever.search` 在检索前，若 embedder `needs_fit()`，就用**同一份语料**重新 `fit`——确定性 fit（按 df 降序建词表）保证跨进程维度一致，向量可对齐。（本地/API embedder 无此问题。）

## 5. 命令

```bash
python -m linuxdo_bot --backfill --pages 20   # 历史回填（断点续跑）
python -m linuxdo_bot --reindex               # 建/补向量索引
python -m linuxdo_bot --ask "codex 额度超限怎么办"   # 离线自检
```

运行中的机器人：用户发 `/ask 问题` 即时检索问答。

## 6. 合规

- 只索引**公开主题**（标题 + 摘要）；答案**只做摘要 + 引用链接**，不整段转载正文。
- 采集源统一走合规客户端（限速 + 退避）；TG 频道源零压力（数据来自 TG CDN）。
