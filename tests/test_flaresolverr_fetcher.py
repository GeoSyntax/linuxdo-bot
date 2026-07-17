"""FlareSolverr fetcher 单元测试（mock，不依赖真实服务）。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from zhihu_crawler.sources.flaresolverr_fetcher import FlareSolverrFetcher


# ── _solve_cf ──

class TestSolveCf:
    def test_success(self):
        """过盾成功后 session 注入 cookies 和 UA。"""
        fetcher = FlareSolverrFetcher()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "solution": {
                "userAgent": "TestAgent/1.0",
                "cookies": [
                    {"name": "cf_clearance", "value": "abc123",
                     "domain": "linux.do", "path": "/"},
                    {"name": "csrftoken", "value": "xyz",
                     "domain": "linux.do", "path": "/"},
                ],
            },
        }

        with patch("zhihu_crawler.sources.flaresolverr_fetcher.requests.post",
                   return_value=mock_resp):
            result = fetcher._solve_cf("https://linux.do/latest.json")

        assert result is True
        assert "linux.do" in fetcher._solved_domains
        assert fetcher._ua == "TestAgent/1.0"
        assert fetcher._session.headers["User-Agent"] == "TestAgent/1.0"
        # cookies 已注入
        assert "cf_clearance" in str(fetcher._session.cookies)

    def test_failure_status(self):
        """FlareSolverr 返回非 ok 状态。"""
        fetcher = FlareSolverrFetcher()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"status": "error", "message": "timeout"}

        with patch("zhihu_crawler.sources.flaresolverr_fetcher.requests.post",
                   return_value=mock_resp):
            result = fetcher._solve_cf("https://linux.do/latest.json")

        assert result is False

    def test_connection_error(self):
        """FlareSolverr 服务不可用。"""
        fetcher = FlareSolverrFetcher()

        import requests as req
        with patch("zhihu_crawler.sources.flaresolverr_fetcher.requests.post",
                   side_effect=req.ConnectionError("refused")):
            result = fetcher._solve_cf("https://linux.do/latest.json")

        assert result is False

    def test_empty_cookies(self):
        """FlareSolverr 返回空 cookies。"""
        fetcher = FlareSolverrFetcher()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "solution": {"userAgent": "Test/1.0", "cookies": []},
        }

        with patch("zhihu_crawler.sources.flaresolverr_fetcher.requests.post",
                   return_value=mock_resp):
            result = fetcher._solve_cf("https://linux.do/latest.json")

        assert result is False


# ── _is_cf_challenge ──

class TestIsCfChallenge:
    def test_403(self):
        fetcher = FlareSolverrFetcher()
        assert fetcher._is_cf_challenge("", 403) is True

    def test_503(self):
        fetcher = FlareSolverrFetcher()
        assert fetcher._is_cf_challenge("", 503) is True

    def test_just_a_moment(self):
        fetcher = FlareSolverrFetcher()
        assert fetcher._is_cf_challenge("<title>Just a moment...</title>") is True

    def test_normal_json(self):
        fetcher = FlareSolverrFetcher()
        assert fetcher._is_cf_challenge('{"topic_list":{"topics":[]}}') is False


# ── get_text ──

class TestGetText:
    def test_direct_success(self):
        """cookie 有效时直接用 session 发请求。"""
        fetcher = FlareSolverrFetcher()
        fetcher._solved_domains.add("linux.do")
        import time
        fetcher._cookie_expires["linux.do"] = time.time() + 3600

        mock_resp = MagicMock()
        mock_resp.text = '{"ok": true}'
        mock_resp.status_code = 200

        with patch.object(fetcher._session, "get", return_value=mock_resp):
            result = fetcher.get_text("https://linux.do/latest.json")

        assert result == '{"ok": true}'

    def test_cf_challenge_retries_solve(self):
        """cookie 过期遇到 CF 挑战后重新过盾。"""
        fetcher = FlareSolverrFetcher()
        fetcher._solved_domains.add("linux.do")
        import time
        fetcher._cookie_expires["linux.do"] = time.time() + 3600

        # 第一次请求返回 CF 挑战
        cf_resp = MagicMock()
        cf_resp.text = "<title>Just a moment...</title>"
        cf_resp.status_code = 403

        # 过盾成功
        fs_resp = MagicMock()
        fs_resp.raise_for_status = MagicMock()
        fs_resp.json.return_value = {
            "status": "ok",
            "solution": {
                "userAgent": "New/1.0",
                "cookies": [{"name": "cf_clearance", "value": "new",
                             "domain": "linux.do", "path": "/"}],
            },
        }

        # 过盾后请求成功
        ok_resp = MagicMock()
        ok_resp.text = '{"data": "ok"}'
        ok_resp.status_code = 200

        call_count = 0

        def mock_session_get(url, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return cf_resp
            return ok_resp

        with patch.object(fetcher._session, "get", side_effect=mock_session_get), \
             patch("zhihu_crawler.sources.flaresolverr_fetcher.requests.post",
                   return_value=fs_resp):
            result = fetcher.get_text("https://linux.do/t/123.json")

        assert result == '{"data": "ok"}'


# ── set_proxy ──

class TestSetProxy:
    def test_clears_state(self):
        fetcher = FlareSolverrFetcher()
        fetcher._solved_domains.add("linux.do")
        fetcher._cookie_expires["linux.do"] = 999

        fetcher.set_proxy("http://new:8080")

        assert fetcher._proxy == "http://new:8080"
        assert len(fetcher._solved_domains) == 0

    def test_noop_same_proxy(self):
        fetcher = FlareSolverrFetcher(proxy="http://a:1")
        fetcher._solved_domains.add("test")
        fetcher.set_proxy("http://a:1")
        assert "test" in fetcher._solved_domains


# ── close ──

class TestClose:
    def test_cleanup(self):
        fetcher = FlareSolverrFetcher()
        fetcher._solved_domains.add("a")
        fetcher._cookie_expires["a"] = 999
        fetcher.close()
        assert len(fetcher._solved_domains) == 0
        assert len(fetcher._cookie_expires) == 0


# ── factory ──

class TestFactory:
    def test_playwright_mode(self):
        from zhihu_crawler.sources.linuxdo import create_fetcher
        fetcher = create_fetcher("playwright")
        from zhihu_crawler.sources.browser_fetcher import BrowserFetcher
        assert isinstance(fetcher, BrowserFetcher)

    def test_flaresolverr_mode(self):
        from zhihu_crawler.sources.linuxdo import create_fetcher
        from zhihu_crawler.sources.flaresolverr_fetcher import FlareSolverrFetcher
        fetcher = create_fetcher("flaresolverr")
        assert isinstance(fetcher, FlareSolverrFetcher)

    def test_warp_mode(self):
        from zhihu_crawler.sources.linuxdo import create_fetcher
        from zhihu_crawler.sources.warp_fetcher import WARPFetcher
        fetcher = create_fetcher("warp")
        assert isinstance(fetcher, WARPFetcher)
