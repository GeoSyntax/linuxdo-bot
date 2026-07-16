"""演示 Web 服务：把项目真实能力暴露成 HTTP 接口 + 托管前端。

每个接口都调用 zhihu_crawler 的真实模块，前端展示的是**真实运行结果**，
不是写死的假数据。

启动：
    python -m webapp.server
    # 浏览器打开 http://127.0.0.1:8000
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from flask import Flask, jsonify, request, send_from_directory

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from zhihu_crawler import fixtures
from zhihu_crawler.ai import ContentCleaner
from zhihu_crawler.compliance import RobotsGate, TokenBucket
from zhihu_crawler.config import get_config
from zhihu_crawler.distributed import BloomFilter
from zhihu_crawler.models import Answer
from zhihu_crawler.client import ZhihuClient
from zhihu_crawler.parser import parse_search_api
from zhihu_crawler.signature import _md5_hex, build_x_zse_96, build_signed_headers, zhihu_encrypt
from zhihu_crawler.sources import REGISTRY

app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"), static_url_path="")

_config = get_config()
_cleaner = ContentCleaner(_config)


# ----------------------------- 前端 -----------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ----------------------- 1. 签名逆向演示 -----------------------
@app.post("/api/signature")
def api_signature():
    data = request.get_json(force=True)
    path = data.get("path", "/api/v4/search_v3?t=general&q=python&limit=5")
    d_c0 = data.get("d_c0", "AABxxxxxxxxxxxxxxxxxxxxxxxxxxxx=")

    plain = f"101_3_3.0+{path}+{d_c0}"
    digest = _md5_hex(plain)
    enc = zhihu_encrypt(digest)
    sig = build_x_zse_96(path, d_c0)
    headers = build_signed_headers(path, d_c0, "Mozilla/5.0 ...Chrome/120")
    return jsonify({
        "steps": [
            {"n": 1, "title": "拼接原文串", "value": plain},
            {"n": 2, "title": "MD5", "value": digest},
            {"n": 3, "title": "自定义密码器（AST 反混淆读出常量后复现）", "value": enc},
            {"n": 4, "title": "拼版本前缀 → x-zse-96", "value": sig},
        ],
        "headers": headers,
        "deterministic": build_x_zse_96(path, d_c0) == sig,
    })


# ------------------------ 2. AI 清洗演示 ------------------------
@app.post("/api/clean")
def api_clean():
    data = request.get_json(force=True)
    html = data.get("html", "")
    t0 = time.time()
    markdown, sentiment = _cleaner.clean_text(html)
    return jsonify({
        "provider": _cleaner.provider.name,
        "markdown": markdown,
        "sentiment": sentiment,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    })


# ---------------------- 3. 布隆去重演示 ----------------------
@app.post("/api/dedup")
def api_dedup():
    data = request.get_json(force=True)
    capacity = int(data.get("capacity", 100_000_000))
    error_rate = float(data.get("error_rate", 0.01))
    sample = data.get("urls", [])

    bf = BloomFilter(capacity=min(capacity, 1_000_000), error_rate=error_rate)
    results = []
    for u in sample:
        seen = bf.add(u)
        results.append({"url": u, "duplicate": seen})

    # 用请求的真实容量估算内存（不真的分配上亿位）
    from zhihu_crawler.distributed.dedup import _optimal_params
    m, k = _optimal_params(capacity, error_rate)
    set_bytes = capacity * 80  # 假设每 URL ~80B
    return jsonify({
        "capacity": capacity,
        "error_rate": error_rate,
        "bits": m,
        "hashes": k,
        "bloom_mb": round(m / 8 / 1024 / 1024, 1),
        "set_mb": round(set_bytes / 1024 / 1024, 1),
        "saving_x": round(set_bytes / (m / 8), 1),
        "results": results,
    })


# --------------------- 4. 合规内核演示 ---------------------
@app.post("/api/compliance")
def api_compliance():
    data = request.get_json(force=True)
    rps = float(data.get("rps", 0.5))
    n = min(int(data.get("n", 5)), 10)

    bucket = TokenBucket(rate=rps, capacity=1)
    timeline = []
    start = time.monotonic()
    for i in range(n):
        waited = bucket.acquire()
        timeline.append({
            "req": i + 1,
            "waited_s": round(waited, 2),
            "at_s": round(time.monotonic() - start, 2),
        })
    return jsonify({"rps": rps, "timeline": timeline})


@app.get("/api/robots")
def api_robots():
    """真实读取知乎 robots 判定（合规内核核心）。"""
    gate = RobotsGate(enabled=True)
    paths = ["/api/v4/search_v3", "/question/", "/search", "/"]
    return jsonify({
        "results": [
            {"path": p, "allowed": gate.can_fetch("https://www.zhihu.com" + p)}
            for p in paths
        ]
    })


# --------------------- 5. 真实反爬实测 ---------------------
@app.get("/api/recon")
def api_recon():
    from zhihu_crawler.recon import run_recon
    force = request.args.get("force") == "1"
    return jsonify(run_recon(force=force))


# ------------------------- 概览统计 -------------------------
@app.post("/api/pipeline")
def api_pipeline():
    """端到端流水线演示：解析 → 去重 → 校验 → AI 清洗（用知乎同构样例数据）。

    走的是项目真实模块（parser / BloomFilter / Answer.validate / ContentCleaner），
    展示完整数据流，不依赖抓生产环境。
    """
    data = request.get_json(force=True)
    limit = int(data.get("limit", 5))
    stages = {}

    raw = fixtures.search_v3("python", limit)
    parsed = parse_search_api(raw)
    stages["fetched"] = len(raw["data"])
    stages["parsed"] = len(parsed)

    bloom = BloomFilter(capacity=100_000, error_rate=0.01)
    deduped = [a for a in parsed if not bloom.add(a.fingerprint)]
    stages["after_dedup"] = len(deduped)

    valid = [a for a in deduped if a.is_valid()]
    stages["valid"] = len(valid)

    cleaned = _cleaner.clean_batch(valid)
    stages["cleaned"] = len(cleaned)

    records = [{
        "answer_id": a.answer_id,
        "question_title": a.question_title,
        "author": a.author,
        "sentiment": a.sentiment,
        "voteup_count": a.voteup_count,
        "markdown": a.content_markdown,
    } for a in cleaned]
    return jsonify({"provider": _cleaner.provider.name, "stages": stages, "records": records})


@app.post("/api/collect")
def api_collect():
    """真实多源采集（对官方 API 发真实请求）→ 去重 → 清洗 → 返回。

    合法合规：Hacker News / arXiv 官方 API，限速受合规客户端约束。
    """
    from zhihu_crawler.distributed import BloomFilter
    data = request.get_json(force=True)
    source_name = data.get("source", "hackernews")
    query = data.get("query", "top")
    limit = min(int(data.get("limit", 5)), 10)

    src_cls = REGISTRY.get(source_name)
    if not src_cls:
        return jsonify({"error": f"未知源 {source_name}"}), 400

    bloom = BloomFilter(capacity=100_000, error_rate=0.01)
    items, fetched = [], 0
    with ZhihuClient(_config) as client:
        source = src_cls(client)
        try:
            for it in source.fetch(query, limit):
                fetched += 1
                if bloom.add(it.fingerprint):
                    continue
                _cleaner.clean_item(it)
                items.append(it)
        finally:
            if hasattr(source, "close"):
                source.close()  # 释放浏览器型源(linux.do)

    records = [{
        "source": it.source, "title": it.title, "author": it.author,
        "score": it.score, "comment_count": it.comment_count,
        "url": it.url, "sentiment": it.sentiment or "-",
        "tags": it.tags, "markdown": it.content_markdown[:200],
    } for it in items]
    return jsonify({
        "source": source_name, "fetched": fetched,
        "kept": len(items), "provider": _cleaner.provider.name,
        "records": records,
    })


@app.get("/api/overview")
def api_overview():
    return jsonify({
        "ai_provider": _cleaner.provider.name,
        "storage_backend": _config.storage.backend,
        "rps": _config.compliance.requests_per_second,
        "respect_robots": _config.compliance.respect_robots,
    })


if __name__ == "__main__":
    print("演示服务启动: http://127.0.0.1:8000")
    app.run(host="127.0.0.1", port=8000, debug=False)
