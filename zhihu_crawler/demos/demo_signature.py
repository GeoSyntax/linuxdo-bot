"""离线演示：签名算法复现（无需联网）。

面试现场可跑，展示 x-zse-96 的端到端生成 + 头部构造。
"""
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文/符号乱码或崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ..signature import build_signed_headers, build_x_zse_96, zhihu_encrypt, _md5_hex


def main() -> None:
    print("=" * 60)
    print("知乎签名 x-zse-96 复现演示")
    print("=" * 60)

    path = "/api/v4/search_v3?t=general&q=python&correction=1&offset=0&limit=5"
    d_c0 = "AABxxxxxxxxxxxxxxxxxxxxxxxxxxxx="  # 示例设备标识

    print(f"\n[输入]")
    print(f"  path+query : {path}")
    print(f"  d_c0       : {d_c0}")

    plain = f"101_3_3.0+{path}+{d_c0}"
    print(f"\n[步骤1] 拼接原文串")
    print(f"  {plain}")

    digest = _md5_hex(plain)
    print(f"\n[步骤2] MD5")
    print(f"  {digest}")

    enc = zhihu_encrypt(digest)
    print(f"\n[步骤3] 自定义密码器（复现自 JS，AST 反混淆读出常量）")
    print(f"  {enc}")

    sig = build_x_zse_96(path, d_c0)
    print(f"\n[步骤4] 拼版本前缀 -> x-zse-96")
    print(f"  {sig}")

    print(f"\n[最终] 完整签名请求头：")
    headers = build_signed_headers(path, d_c0, "Mozilla/5.0 ...Chrome/120")
    for k, v in headers.items():
        print(f"  {k}: {v[:70]}")

    # 确定性验证：同输入必得同输出
    assert build_x_zse_96(path, d_c0) == sig
    print("\n✅ 确定性校验通过：相同输入稳定复现相同签名")
    print("   （方法论见 docs/reverse-engineering.md）")


if __name__ == "__main__":
    main()
