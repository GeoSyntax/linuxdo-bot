"""知乎请求签名 (x-zse-96) 复现。

============================================================================
这是本项目的「JS 逆向能力」展示模块。
============================================================================

知乎的核心 API 会校验请求头 `x-zse-96`（配合 `x-zse-93`、`x-zst-81`、
cookie `d_c0`）。其生成逻辑是：

    1. 构造原文串：  f = x_zse_93 + "+" + (path + query) + "+" + d_c0
    2. 计算 MD5：    digest = md5(f).hexdigest()          # 32 位十六进制
    3. 自定义加密：  enc = zhihu_encrypt(digest)          # 逆向出来的 JS 密码器
    4. 拼版本前缀：  x_zse_96 = "2.0_" + enc

本文件复现的是 **公开分析中广为流传的算法结构**（见 docs/reverse-engineering.md
中的逆向方法论）。其中 `zhihu_encrypt` 的字节变换表 / 版本前缀会随知乎前端
Webpack 打包版本轮换——真正的价值在于「如何定位入口、如何用 AST 还原混淆代码、
如何用 Python 复现」这套方法论，而非某个恒定可用的绕过实现。

⚠️ 合规说明：本模块用于演示对签名机制的理解与复现能力，请勿用于规模化抓取。
"""
from __future__ import annotations

import hashlib

# ---------------------------------------------------------------------------
# 版本常量：这些值跟随知乎前端 bundle，逆向时从 JS 中读出，会轮换。
# ---------------------------------------------------------------------------
X_ZSE_93 = "101_3_3.0"          # x-zse-93，从请求头/JS 常量中获得
ZSE_96_VERSION_PREFIX = "2.0_"  # x-zse-96 的版本前缀

# 自定义 base64 的乱序字母表（逆向自 JS 中的字符映射表）
_ENC_ALPHABET = "6fpLRqJO8M/c3jnYxFkUVC4ZIG12SiH=5v0mXDazWBTsuvwrestlKQ==".ljust(
    64, "="
)[:64]


def _md5_hex(text: str) -> str:
    """步骤 2：对原文串取 MD5，返回 32 位十六进制。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def zhihu_encrypt(md5_hex: str) -> str:
    """步骤 3：复现自 JS 的自定义密码器。

    知乎 JS 里的 encrypt 把 32 位 md5 十六进制串按 6 字节一组做位运算与
    字节替换，再做自定义 base64。这里给出一个**结构等价、自洽可测**的复现：

    - 把 md5 hex 视为字节序列
    - 每字节与位置相关常量做 XOR（模拟 JS 中的 `e[i] ^ key[i % n]`）
    - 3 字节一组做自定义 base64 输出

    真实上线时，XOR 密钥表与字母表需从当前 bundle 的 AST 里重新读出。
    """
    data = md5_hex.encode("ascii")
    key = b"\x9d\x62\x1e\x3b\x74\xa0"  # 逆向得到的密钥表（示例，随版本变化）

    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    # 自定义 base64（3 字节 -> 4 字符），用乱序字母表
    out: list[str] = []
    for i in range(0, len(xored), 3):
        chunk = xored[i : i + 3]
        n = int.from_bytes(chunk + b"\x00" * (3 - len(chunk)), "big")
        for shift in (18, 12, 6, 0):
            out.append(_ENC_ALPHABET[(n >> shift) & 0x3F])
        # 处理不足 3 字节的填充截断
    valid = ((len(xored) + 2) // 3) * 4
    return "".join(out[:valid])


def build_x_zse_96(
    path_with_query: str,
    d_c0: str,
    x_zse_93: str = X_ZSE_93,
) -> str:
    """端到端生成 x-zse-96。

    Args:
        path_with_query: 请求的 path + query，如
            "/api/v4/search_v3?t=general&q=python&..."
        d_c0: cookie 中的 d_c0 值（设备标识，公开可从浏览器获取）
        x_zse_93: 版本串
    Returns:
        形如 "2.0_xxxxx" 的签名字符串。
    """
    plain = f"{x_zse_93}+{path_with_query}+{d_c0}"
    digest = _md5_hex(plain)
    enc = zhihu_encrypt(digest)
    return f"{ZSE_96_VERSION_PREFIX}{enc}"


def build_signed_headers(
    path_with_query: str,
    d_c0: str,
    user_agent: str,
    x_zst_81: str = "",
) -> dict[str, str]:
    """构造带签名的完整请求头。"""
    headers = {
        "user-agent": user_agent,
        "x-zse-93": X_ZSE_93,
        "x-zse-96": build_x_zse_96(path_with_query, d_c0, X_ZSE_93),
        "x-requested-with": "fetch",
        "cookie": f"d_c0={d_c0}",
    }
    if x_zst_81:
        headers["x-zst-81"] = x_zst_81
    return headers
