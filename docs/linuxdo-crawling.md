# linux.do 采集实录（重点展示）

> 本文档记录对 **linux.do**（基于 Discourse 的中文技术社区）的合规采集实现。这是本项目"面对真实反爬、如何在合规前提下拿到数据"的核心案例。

---

## 1. 目标与实测结论

linux.do 是 Discourse 论坛。Discourse 有一个官方特性：**几乎任何页面 URL 加 `.json` 就返回该页的结构化数据**（这是它前端自身取数的方式）。

**上手前先实测（不凭假设）**，结果：

| 探测项 | 实测结果 | 结论 |
|---|---|---|
| `robots.txt` 对 `/latest.json`、`/categories.json`、`/t/*.json`、`/c/` | **全部允许（True）** | ✅ 合规基础成立 |
| 直接 `requests` 拉 `.json` | `403` + `Just a moment...`（Cloudflare） | ⚠️ 有 CF 托管挑战 |
| `curl_cffi`（TLS 指纹伪装 chrome120） | 仍 `403` | ⚠️ 托管挑战需执行 JS，指纹伪装无效 |
| **Playwright 真实浏览器** | **200 + 真实 JSON（30 主题）** | ✅ 可行 |

**核心判断**：合规层面 linux.do **允许**采集这些路径；技术层面卡在 Cloudflare 托管挑战，而**突破它最正当的方式是用真实浏览器**——因为浏览器本就会执行挑战 JS，这是"以真实用户方式访问 robots 允许的公开内容"，不是逆向签名、不是伪造。

---

## 2. 实现方案

```
LinuxDoSource
   └── BrowserFetcher (Playwright, 复用令牌桶限速)
         └── 真实 Chromium → 访问 https://linux.do/latest.json
               → 等待 CF 挑战通过（title 不再含 "Just a moment"）
               → 取 body 文本（即 JSON）→ 解析 Discourse 结构
```

- **`sources/browser_fetcher.py`**：惰性启动 Playwright，导航→等挑战通过→返回正文；构造时传入令牌桶，**限速照旧生效**。
- **`sources/linuxdo.py`**：解析 Discourse 的 `topic_list.topics`，映射为统一 `Item`（浏览数→score、回复数→comment_count、楼主→author、标签→tags）。

### 解析要点（踩过的真实坑）

1. **作者提取**：Discourse 的 `posters[].description` 里楼主标记是 `"Original Poster"`，但**文案可能本地化**。策略：先匹配 `"Original"`，失败则回退 `posters[0]`（默认第一个即楼主）。
2. **tags 类型不一**：有时是字符串数组，有时是 `{name:..}` 字典数组。统一做类型判断转字符串，否则 `",".join` 直接崩。
3. **未过挑战兜底**：若返回不是 JSON（挑战没过），记录前 120 字告警并返回空，不让整条流水线挂掉。

---

## 3. 运行

```bash
pip install playwright
python -m playwright install chromium        # 一次性，装浏览器

# 命令行
python -m zhihu_crawler.run_multi --source linuxdo --query latest --limit 5
python -m zhihu_crawler.run_multi --source linuxdo --query develop --limit 5   # 按分类

# Web 界面
python -m webapp.server   # → 「真实采集」面板选 linux.do
```

**真实采集样例**（某次运行）：

| 标题 | 作者 | 浏览 | 回复 |
|---|---|---|---|
| 请不要把互联网上的戾气带来这里！ | neo | 445,993 | 6,478 |
| 《秘密花园园丁邀请函》 | neo | 316,922 | 3,994 |
| 现在用 cursor 的人还多吗？ | xiyue666 | 555 | 20 |

---

## 4. 合规边界

- ✅ **只采公开列表/主题**，robots 明确允许；
- ✅ **限速克制**，不给社区服务器压力；
- ✅ 用真实浏览器过挑战 = **模拟真实用户访问**，非逆向 CF 算法；
- ⚠️ 若要采**主题正文全文**（二跳 `/t/{slug}/{id}.json`），同样受 robots 允许，但应进一步降低频次、遵守社区《用户协议》，不做规模化转载。

## 5. 技术要点

> "linux.do 前面有 Cloudflare 托管挑战，普通请求和 TLS 指纹伪装都过不去。我先实测确认它的 robots 是**允许**爬 `.json` 接口的——所以合规上没问题；技术上我用 Playwright 真实浏览器去过挑战，因为浏览器本来就会执行那段挑战 JS，这等于以真实用户的方式访问被允许的公开内容，而不是去逆向破解 Cloudflare。限速、去重、AI 清洗全都复用我这套框架的合规内核。这体现的是：**面对反爬，先判断合规边界，再用最正当的技术手段拿数据。**"
