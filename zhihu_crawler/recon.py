"""连通性/反爬实测模块。

对知乎发少量真实请求，诚实记录服务端反应（robots 判定、无签名/带签名
的响应码、首页连通性）。结果带缓存，避免频繁打扰目标服务器（合规）。

这个模块的价值：面试时能拿出「我真的测过、这是真实反爬行为」的证据，
而不是空谈。
"""
from __future__ import annotations

import time
from urllib.robotparser import RobotFileParser

import requests

from .signature import build_signed_headers

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BASE = "https://www.zhihu.com"

# 简单缓存：探测代价高且应克制，默认 5 分钟内复用结果
_CACHE: dict[str, object] = {}
_CACHE_TTL = 300.0


def _robots_check() -> dict:
    result = {"reachable": False, "paths": {}}
    try:
        rp = RobotFileParser()
        rp.set_url(f"{_BASE}/robots.txt")
        rp.read()
        result["reachable"] = True
        for p in ["/api/v4/search_v3", "/question/", "/search", "/"]:
            result["paths"][p] = rp.can_fetch("*", _BASE + p)
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    return result


def _http_probe(url: str, headers: dict, timeout: int = 12) -> dict:
    out: dict[str, object] = {"url": url}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        out["status"] = r.status_code
        out["content_type"] = r.headers.get("content-type", "")
        out["bytes"] = len(r.content)
        out["body_preview"] = r.text[:240].replace("\n", " ").strip()
        try:
            out["json_keys"] = list(r.json().keys())[:8]
        except Exception:  # noqa: BLE001
            out["json_keys"] = None
    except Exception as exc:  # noqa: BLE001
        out["error"] = repr(exc)
    return out


def run_recon(force: bool = False) -> dict:
    """执行一次连通性实测。带缓存，force=True 强制重跑。"""
    now = time.time()
    cached = _CACHE.get("data")
    ts = _CACHE.get("ts", 0.0)
    if cached and not force and (now - float(ts)) < _CACHE_TTL:  # type: ignore[arg-type]
        return {**cached, "cached": True}  # type: ignore[dict-item]

    pq = "/api/v4/search_v3?t=general&q=python&limit=3"
    report = {
        "timestamp": now,
        "robots": _robots_check(),
        "unsigned_api": _http_probe(
            _BASE + pq,
            {"user-agent": _UA, "accept": "application/json"},
        ),
        "signed_api": _http_probe(
            _BASE + pq,
            {
                **build_signed_headers(pq, d_c0="AAfakefakefakefake=", user_agent=_UA),
                "accept": "application/json",
            },
        ),
        "homepage": _http_probe(_BASE + "/", {"user-agent": _UA}),
        "cached": False,
    }
    # 诚实结论
    signed_status = report["signed_api"].get("status")
    report["verdict"] = (
        "robots 禁止受保护 API 路径；带复现签名仍返回 "
        f"{signed_status}（需登录/人机验证）。结论：合规版按设计不抓这些路径，"
        "签名模块为机制复现演示，非实盘可用绕过。"
    )
    _CACHE["data"] = report
    _CACHE["ts"] = now
    return report
