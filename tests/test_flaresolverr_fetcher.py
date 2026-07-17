"""FlareSolverr fetcher 单元测试（mock，不依赖真实服务）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from zhihu_crawler.sources.flaresolverr_fetcher import FlareSolverrFetcher


def _fs_ok(html="<p>Hello</p>", status=200):
    """构造 FlareSolverr 成功响应。"""
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "status": "ok",
        "solution": {"response": html, "status": status},
    }
    return mock


def _fs_err(msg="error"):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"status": "error", "message": msg}
    return mock


def _fs_create_ok():
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"status": "ok"}
    return mock


class TestSessionLifecycle:
    def test_creates_session_on_first_request(self):
        fetcher = FlareSolverrFetcher()
        with patch.object(fetcher._http, "post") as m:
            # session.create -> request.get
            m.side_effect = [_fs_create_ok(), _fs_ok('{"data":1}')]
            result = fetcher.get_text("https://linux.do/latest.json")
        assert result == '{"data":1}'
        assert fetcher._session_id is not None

    def test_reuses_session(self):
        fetcher = FlareSolverrFetcher()
        with patch.object(fetcher._http, "post") as m:
            m.side_effect = [_fs_create_ok(), _fs_ok('"a"'), _fs_ok('"b"')]
            fetcher.get_text("https://linux.do/t/1.json")
            fetcher.get_text("https://linux.do/t/2.json")
        # 第二次不应再 create
        assert m.call_count == 3  # 1 create + 2 request.get

    def test_close_destroys_session(self):
        fetcher = FlareSolverrFetcher()
        fetcher._session_id = "test-123"
        with patch.object(fetcher._http, "post", return_value=_fs_create_ok()) as m:
            fetcher.close()
        m.assert_called_once()
        assert fetcher._session_id is None


class TestGetText:
    def test_success(self):
        fetcher = FlareSolverrFetcher()
        with patch.object(fetcher._http, "post") as m:
            m.side_effect = [_fs_create_ok(), _fs_ok('{"ok":true}')]
            result = fetcher.get_text("https://linux.do/latest.json")
        assert result == '{"ok":true}'

    def test_cf_challenge_retries_with_new_session(self):
        fetcher = FlareSolverrFetcher()
        with patch.object(fetcher._http, "post") as m:
            m.side_effect = [
                _fs_create_ok(),                      # session create
                _fs_ok("<title>Just a moment</title>", 403),  # CF challenge
                _fs_create_ok(),                      # destroy old session
                _fs_create_ok(),                      # re-create session
                _fs_ok('{"ok":true}'),                # success
            ]
            result = fetcher.get_text("https://linux.do/t/1.json")
        assert result == '{"ok":true}'

    def test_flaresolverr_error_raises(self):
        fetcher = FlareSolverrFetcher()
        with patch.object(fetcher._http, "post") as m:
            m.side_effect = [_fs_create_ok(), _fs_err("timeout"), _fs_err("timeout")]
            with pytest.raises(ConnectionError):
                fetcher.get_text("https://linux.do/t/1.json")

    def test_bucket_acquired(self):
        bucket = MagicMock()
        fetcher = FlareSolverrFetcher(bucket=bucket)
        with patch.object(fetcher._http, "post") as m:
            m.side_effect = [_fs_create_ok(), _fs_ok('"ok"')]
            fetcher.get_text("https://linux.do/latest.json")
        bucket.acquire.assert_called_once()

    def test_unreachable_raises(self):
        fetcher = FlareSolverrFetcher()
        import requests as req
        with patch.object(fetcher._http, "post", side_effect=req.ConnectionError("refused")):
            with pytest.raises(req.ConnectionError):
                fetcher.get_text("https://linux.do/latest.json")


class TestProxy:
    def test_set_proxy_destroys_session(self):
        fetcher = FlareSolverrFetcher()
        fetcher._session_id = "test"
        with patch.object(fetcher._http, "post", return_value=_fs_create_ok()):
            fetcher.set_proxy("http://new:8080")
        assert fetcher._proxy == "http://new:8080"
        assert fetcher._session_id is None

    def test_noop_same_proxy(self):
        fetcher = FlareSolverrFetcher(proxy="http://a:1")
        fetcher._session_id = "keep"
        fetcher.set_proxy("http://a:1")
        assert fetcher._session_id == "keep"


class TestFactory:
    def test_playwright_mode(self):
        from zhihu_crawler.sources.linuxdo import create_fetcher
        from zhihu_crawler.sources.browser_fetcher import BrowserFetcher
        assert isinstance(create_fetcher("playwright"), BrowserFetcher)

    def test_flaresolverr_mode(self):
        from zhihu_crawler.sources.linuxdo import create_fetcher
        from zhihu_crawler.sources.flaresolverr_fetcher import FlareSolverrFetcher
        assert isinstance(create_fetcher("flaresolverr"), FlareSolverrFetcher)

    def test_warp_mode(self):
        from zhihu_crawler.sources.linuxdo import create_fetcher
        from zhihu_crawler.sources.warp_fetcher import WARPFetcher
        assert isinstance(create_fetcher("warp"), WARPFetcher)
