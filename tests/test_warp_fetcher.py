"""WARP fetcher 单元测试（mock，不依赖真实 WARP 服务）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from zhihu_crawler.sources.warp_fetcher import WARPFetcher


class TestWARPFetcher:
    def test_direct_success(self):
        """WARP 直连成功（无 CF 挑战）。"""
        fetcher = WARPFetcher()

        mock_resp = MagicMock()
        mock_resp.text = '{"ok": true}'
        mock_resp.status_code = 200

        with patch.object(fetcher._session, "get", return_value=mock_resp):
            result = fetcher.get_text("https://linux.do/latest.json")

        assert result == '{"ok": true}'

    def test_cf_challenge_fallback_to_flaresolverr(self):
        """WARP 遇到 CF 挑战时降级到 FlareSolverr。"""
        fallback = MagicMock()
        fallback.get_text.return_value = '{"fallback": true}'

        fetcher = WARPFetcher(fallback_fetcher=fallback)

        mock_resp = MagicMock()
        mock_resp.text = "<title>Just a moment...</title>"
        mock_resp.status_code = 403

        with patch.object(fetcher._session, "get", return_value=mock_resp):
            result = fetcher.get_text("https://linux.do/latest.json")

        assert result == '{"fallback": true}'
        fallback.get_text.assert_called_once_with("https://linux.do/latest.json", attempts=2)

    def test_connection_error_fallback(self):
        """WARP 连接失败时降级到 fallback。"""
        import requests as req
        fallback = MagicMock()
        fallback.get_text.return_value = '{"fb": true}'

        fetcher = WARPFetcher(fallback_fetcher=fallback)

        with patch.object(fetcher._session, "get",
                          side_effect=req.ConnectionError("timeout")):
            result = fetcher.get_text("https://linux.do/latest.json")

        assert result == '{"fb": true}'

    def test_no_fallback_raises(self):
        """无 fallback 且 WARP 被拦截时抛异常。"""
        fetcher = WARPFetcher()

        mock_resp = MagicMock()
        mock_resp.text = "<title>Just a moment...</title>"
        mock_resp.status_code = 403

        with patch.object(fetcher._session, "get", return_value=mock_resp):
            with pytest.raises(ConnectionError, match="无 fallback"):
                fetcher.get_text("https://linux.do/latest.json")

    def test_set_proxy(self):
        fetcher = WARPFetcher(warp_proxy="socks5://a:1")
        fetcher.set_proxy("socks5://b:2")
        assert fetcher._warp_proxy == "socks5://b:2"
        assert fetcher._session.proxies["https"] == "socks5://b:2"

    def test_set_proxy_noop(self):
        fetcher = WARPFetcher(warp_proxy="socks5://a:1")
        fetcher.set_proxy("socks5://a:1")
        # no change
        assert fetcher._warp_proxy == "socks5://a:1"

    def test_close(self):
        fallback = MagicMock()
        fetcher = WARPFetcher(fallback_fetcher=fallback)
        fetcher.close()
        fallback.close.assert_called_once()

    def test_bucket_acquired(self):
        """有 bucket 时先 acquire。"""
        bucket = MagicMock()
        fetcher = WARPFetcher(bucket=bucket)

        mock_resp = MagicMock()
        mock_resp.text = '{"ok": true}'
        mock_resp.status_code = 200

        with patch.object(fetcher._session, "get", return_value=mock_resp):
            fetcher.get_text("https://linux.do/latest.json")

        bucket.acquire.assert_called_once()
