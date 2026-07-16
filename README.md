# linux.do 关键词监控 Telegram 机器人

> **一句话**：定时**合规采集 linux.do 最新主题**，命中你订阅的**关键词**就通过 **Telegram 推送**给你。支持多关键词/AND/OR/正则订阅，用户**本地一键部署**。

> **技术核心**：linux.do 前置 Cloudflare 人机盾（普通请求、TLS 指纹伪装都被 403）——用 **Playwright 真实浏览器过盾**采集其 Discourse `.json` 接口（robots 实测**允许**）。合规采集内核（robots 遵守 + 令牌桶限速 + 退避重试）贯穿始终。

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## ✨ 功能

- 🔔 **关键词订阅推送**：`/sub python`、`/sub ai|llm agent`（空格=且，`|`=或，`/正则/`）
- 🕸️ **合规采集 linux.do**：Playwright 过 Cloudflare 盾，robots 允许的 `.json` 接口，令牌桶限速
- 🧹 **去重**：已见主题 + 已推送记录双重去重，不重复打扰
- 🤖 **Telegram 机器人**：`/sub /unsub /list /latest /help` 命令交互
- 🚀 **本地部署友好**：极简依赖（requests + playwright），`.env` 配置，含 Dockerfile / docker-compose
- 🧪 **无 token 可验证**：`--dry-run` 不需 TG token，对真实 linux.do 跑一轮看命中

---

## ⚖️ 合规声明（请先读）

- ✅ linux.do 的 `robots.txt` **实测允许** `/latest.json`、`/t/*.json`、`/c/` 等路径（见 [`docs/linuxdo-crawling.md`](docs/linuxdo-crawling.md)）
- ✅ 只采**公开主题列表/内容**，不涉及登录态、不涉及私信/隐私
- ✅ **令牌桶限速**（默认约 3 秒 1 次）+ 退避重试，轮询间隔默认 5 分钟，不给社区造成压力
- ✅ 用真实浏览器过 Cloudflare = **模拟真实用户访问被允许的公开内容**，非逆向破解
- ⚠️ 请遵守 linux.do《用户协议》与社区规范，勿规模化转载

---

## 🚀 快速开始（本地部署）

### 方式一：直接跑（推荐先试）

```bash
# 1. 安装依赖（主力源=官方 TG 频道，纯 requests，无需浏览器）
pip install -r requirements.txt

# 2. 【无需 TG token】先验证采集与匹配是否通
python -m linuxdo_bot --dry-run --keyword "gpt|ai|模型" --keyword cursor
#   → 从官方 TG 频道拉一轮 linux.do 最新主题，命中的打印到控制台

# 3.（可选）历史回填 + 建 RAG 索引，让 /ask 能搜到内容
python -m linuxdo_bot --backfill --pages 20   # 断点续跑，可反复运行往前翻
python -m linuxdo_bot --reindex               # 给语料库建向量索引
python -m linuxdo_bot --ask "codex 额度超限怎么办"   # 离线自检问答

# 4. 配置 Telegram token 并启动
cp .env.example .env      # 填入从 @BotFather 获取的 TG_BOT_TOKEN
python -m linuxdo_bot     # 在 TG 里对机器人发 /quick 一键订阅
```

### 方式二：Docker（一键）

```bash
cp .env.example .env          # 填 TG_BOT_TOKEN
docker compose up -d          # 轻量 slim 镜像，纯 requests，无需浏览器
```

### Telegram 命令

| 命令 | 说明 |
|---|---|
| `/subscribe 关键词` | 订阅。`/subscribe python`、`ai\|llm agent`、`/v\d+/`（支持 且/或/正则） |
| `/unsubscribe 关键词` | 取消订阅 |
| `/subscribe_user 用户名` | 关注某用户，TA 发帖就推送 |
| `/unsubscribe_user 用户名` | 取消关注 |
| `/quick` | 一键订阅（inline 按钮：claude/ai/gemini/公益 + 公益大佬） |
| `/ask 问题` | 🔍 AI 搜索社区已有解决方法（论坛搜索的增强版，带原帖引用） |
| `/list` | 查看我的订阅 |
| `/latest [n]` | 立即拉最新 n 条 |
| `/help` | 帮助 |

---

## 🏗️ 架构

```
  Telegram 用户 ──/subscribe /ask /quick──▶ 命令路由 commands.py
        ▲                                        │
        │ 推送/答案(telegram.py)                   │ 读写订阅
        │                                        ▼
        │                              ┌────────────────────┐
        │                              │  存储 store.py       │
        │                              │  订阅 / 关注 / 去重   │
        │                              └────────────────────┘
        │                                        ▲ 命中?(matcher AND/OR/正则)
  ┌─────┴───────────┐   主题    ┌────────────────┴──────────┐
  │  监控循环         │◀─────────│  官方 TG 频道源             │
  │  monitor.py      │  沉淀    │  t.me/s/linuxdoit(纯requests)│ ← 无需 CF 盾
  │  (每 N 分钟)      │─────┐    │  合规客户端: 限速 + 退避     │
  └─────────────────┘     │    └───────────────────────────┘
                          ▼
              ┌────────────────────┐      ┌──────────────────────┐
              │  语料库 corpus.py    │◀────▶│  RAG (/ask)           │
              │  documents + 向量    │ 检索 │  embedder+index+engine │
              │  (SQLite, 断点续填)  │      │  三档: 本地/API/TF-IDF  │
              └────────────────────┘      └──────────────────────┘
```

- **主力源**：`sources/tgchannel.py`（官方 TG 频道网页版，纯 requests、无需 Cloudflare 盾、`?before=` 可回填）。
- **可选源**：`sources/linuxdo.py`（Discourse `.json` + Playwright 过盾，取正文详情用）。
- 底层复用 `zhihu_crawler/` 的合规采集内核（`compliance/` + `client.py`）。

---

## ⚙️ 配置（.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `TG_BOT_TOKEN` | **必填**，@BotFather 获取 | — |
| `LINUXDO_CATEGORIES` | 监控分类：`latest` 或分类 slug，逗号分隔 | `latest` |
| `POLL_INTERVAL` | 采集轮询间隔（秒） | `300` |
| `FETCH_LIMIT` | 每轮取主题数 | `30` |
| `FETCH_DETAIL` | 是否二跳抓正文做更精准匹配 | `false` |
| `REQUESTS_PER_SECOND` | 限速（合规） | `0.33` |
| `HEADLESS` | 浏览器无头（仅 linuxdo 直连源用） | `true` |
| `RAG_EMBED_PROVIDER` | `/ask` 向量化：`tfidf`(零依赖) / `local` / `api` | `tfidf` |
| `RAG_LLM_PROVIDER` | `/ask` 答案生成：`rule`(主题列表) / `ollama` / `openai` | `rule` |
| `RAG_TOP_K` | `/ask` 返回相关主题数 | `5` |

（RAG 完整变量见 `.env.example`。）

---

## 🔍 /ask 智能搜索（RAG）

论坛原生搜索不好用，`/ask` 用**语义检索 + LLM 综合**帮用户快速找到已有解决方法，**答案始终带原帖引用链接**（把流量导回 linux.do，合规）。

- **数据来源**：监控采集的每条主题都沉淀进语料库（`corpus.py`）；`--backfill` 从 TG 频道 `?before=` 往前翻做历史回填（断点续跑）。
- **三档降级，任何环境可跑**：
  - embedding：`local`(sentence-transformers 中文语义) → `api`(OpenAI 兼容) → `tfidf`(纯 numpy，零依赖回退)
  - 生成：`ollama`(本地) → `openai`(云) → `rule`(直接给最相关主题列表，仍比原生搜索好用)
- 运维命令：`--backfill --pages N`（回填）、`--reindex`（建向量索引）、`--ask "问题"`（离线自检）。

详见 [`docs/rag.md`](docs/rag.md)。

---

## 🧩 底层采集引擎（可独立使用）

本项目构建在一套通用的**多源合规采集引擎**之上，除 linux.do 外还内置 Hacker News / arXiv 官方 API 源，以及 AI 清洗、布隆去重、Scrapy-Redis 分布式扩展、知乎签名逆向复现等能力：

```bash
python -m zhihu_crawler.run_multi --source linuxdo,hackernews,arxiv --limit 5
python -m webapp.server     # 可视化演示界面(采集/清洗/去重/合规/反爬实测)
```

详见 [`docs/architecture.md`](docs/architecture.md)、[`docs/linuxdo-crawling.md`](docs/linuxdo-crawling.md)。

---

## 📂 目录结构

```
zhihu/
├── README.md                      # 本文件
├── requirements.txt
├── .env.example                   # ⭐ 环境配置模板（复制为 .env）
├── Dockerfile / docker-compose.yml # ⭐ 一键容器部署
├── config.yaml                    # 采集引擎配置（限速/AI/存储）
├── linuxdo_bot/                   # ⭐⭐ Telegram 机器人应用
│   ├── __main__.py                # 主入口（--dry-run/--backfill/--reindex/--ask）
│   ├── config.py                  # .env 配置加载（含 RAG）
│   ├── monitor.py                 # 监控循环：采集→匹配→分发→沉淀语料库
│   ├── matcher.py                 # 关键词匹配（AND/OR/正则）
│   ├── store.py                   # SQLite：关键词/用户订阅 + 去重
│   ├── corpus.py                  # ⭐ 语料库：文档 + 回填游标
│   ├── backfill.py                # ⭐ 历史回填（TG 频道 ?before= 断点续跑）
│   ├── commands.py                # 命令路由 + inline 回调
│   ├── presets.py                 # 快捷关键词 + 公益大佬预置
│   ├── telegram.py                # 轻量 TG API 客户端（含 inline 键盘）
│   └── rag/                       # ⭐ RAG 智能搜索
│       ├── embedder.py            #   向量化：local/api/tfidf 三档
│       ├── index.py               #   SQLite 向量存储 + numpy 检索
│       ├── retriever.py           #   建索引 / 语义检索
│       └── engine.py              #   /ask：检索→LLM 综合→带引用
├── docs/
│   ├── linuxdo-crawling.md        # ⭐ linux.do 采集实录（过盾方法论）
│   ├── rag.md                     # ⭐ RAG 设计说明
│   ├── architecture.md            # 采集引擎架构
│   ├── reverse-engineering.md     # 知乎签名逆向方法论
│   └── compliance.md              # 合规设计说明
├── zhihu_crawler/
│   ├── config.py                  # 配置加载
│   ├── signature.py               # ⭐ x-zse-96 签名复现
│   ├── client.py                  # 采集会话客户端
│   ├── parser.py                  # 鲁棒解析器
│   ├── models.py                  # 数据模型
│   ├── storage.py                 # 存储（SQLite/MySQL）
│   ├── compliance/
│   │   ├── robots.py              # robots.txt 遵守
│   │   └── throttle.py            # 令牌桶限速 + 退避重试
│   ├── ai/
│   │   ├── cleaner.py             # ⭐ AI 清洗管道
│   │   └── providers.py           # LLM provider 抽象（ollama/api/rule）
│   ├── sources/                  # ⭐ 多源适配器
│   │   ├── tgchannel.py         #   ⭐ 官方 TG 频道（主力，纯 requests）
│   │   ├── linuxdo.py           #   linux.do (Discourse + Playwright 过盾)
│   │   ├── browser_fetcher.py   #   Playwright 过 Cloudflare 抓取器
│   │   ├── hackernews.py        #   Hacker News 官方 API
│   │   └── arxiv.py             #   arXiv 官方 API
│   ├── distributed/dedup.py      # 布隆过滤器去重
│   ├── run_multi.py              # 多源采集入口
│   └── run.py                    # 知乎单机入口（含签名演示）
├── webapp/                        # 采集引擎可视化演示界面
├── scrapy_project/                # Scrapy-Redis 分布式工程
└── tests/                         # 单元测试（90 项）
```

---

## 📌 关键技术点（面试可深挖）

1. **签名机制复现**：分析知乎请求头 `x-zse-96` 的生成逻辑，从 DevTools 定位加密入口，到 Webpack 代码断点、AST 结构化分析混淆代码，最后用 Python 复现。见 [`docs/reverse-engineering.md`](docs/reverse-engineering.md)。
2. **鲁棒解析**：面对知乎多变 DOM（及可能的干扰节点），解析器采用"主选择器 + 多重回退 + 数据校验"三层策略。
3. **分布式去重**：Redis 布隆过滤器，1 亿 URL 仅需 ~171MB 内存（误判率 1%），对比 set 存储省 30x+。
4. **AI 清洗**：LLM 把结构混乱的富文本回答规整为干净 Markdown，剔除广告/灌水，输出情感标签，支撑下游舆情分析。三档 provider（本地 Ollama / 云 API / 纯规则），保证任何环境可运行。

---

## 📄 License

MIT
