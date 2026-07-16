"""签名模块测试：确定性 + 输入敏感性。"""
from zhihu_crawler.signature import build_x_zse_96, build_signed_headers, zhihu_encrypt


def test_signature_deterministic():
    """相同输入 -> 相同签名。"""
    path = "/api/v4/search_v3?q=python"
    dc0 = "AABtest="
    assert build_x_zse_96(path, dc0) == build_x_zse_96(path, dc0)


def test_signature_input_sensitive():
    """不同 path -> 不同签名（签名确实依赖请求内容）。"""
    dc0 = "AABtest="
    s1 = build_x_zse_96("/api/v4/search_v3?q=python", dc0)
    s2 = build_x_zse_96("/api/v4/search_v3?q=java", dc0)
    assert s1 != s2


def test_signature_has_version_prefix():
    sig = build_x_zse_96("/x", "y")
    assert sig.startswith("2.0_")


def test_encrypt_stable():
    digest = "d41d8cd98f00b204e9800998ecf8427e"
    assert zhihu_encrypt(digest) == zhihu_encrypt(digest)


def test_signed_headers_shape():
    h = build_signed_headers("/api/v4/x?q=1", "dc0val", "UA/1.0")
    assert h["x-zse-96"].startswith("2.0_")
    assert h["x-zse-93"]
    assert "d_c0=dc0val" in h["cookie"]
    assert h["user-agent"] == "UA/1.0"
