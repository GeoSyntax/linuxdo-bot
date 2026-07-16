"""本地沙箱端点：以知乎同结构响应，让整条采集流水线真实跑通。

用途：在没有生产授权 / 或用授权测试环境之前，用它验证
    采集 → 解析 → 去重 → AI 清洗 → 存储
的完整链路。它返回的是 fixtures 里的知乎同构样例数据。

启动：
    python -m webapp.sandbox            # 监听 http://127.0.0.1:8901
然后：
    python -m zhihu_crawler.run --keyword python --limit 5 \
        --base-url http://127.0.0.1:8901

如果将来拿到知乎真实测试环境/API，把 --base-url 指过去即可，代码不用改。
"""
from __future__ import annotations

import sys

from flask import Flask, jsonify, request

sys.path.insert(0, ".")
from zhihu_crawler import fixtures  # noqa: E402

app = Flask(__name__)


@app.get("/robots.txt")
def robots():
    # 沙箱允许抓取（与生产相反），便于演示合规内核放行分支
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}


@app.get("/api/v4/search_v3")
def search_v3():
    keyword = request.args.get("q", "python")
    limit = int(request.args.get("limit", 5))
    return jsonify(fixtures.search_v3(keyword, limit))


if __name__ == "__main__":
    print("沙箱端点: http://127.0.0.1:8901  (知乎同结构样例数据)")
    app.run(host="127.0.0.1", port=8901, debug=False)
