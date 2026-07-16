"""离线演示：AI 清洗管道（规则回退模式，无需模型/联网）。

展示把夹带广告灌水的富文本 HTML -> 干净 Markdown + 情感标签。
若本地有 Ollama，把 config.yaml 的 ai.provider 改为 ollama 即走真模型。
"""
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文/符号乱码或崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ..config import get_config
from ..ai import ContentCleaner
from ..models import Answer

SAMPLE_HTML = """
<div class="RichText">
<p>Python 真的很适合做数据采集，生态成熟，requests 和 scrapy 都很好用。</p>
<p>我觉得对新手非常友好，推荐入门。</p>
<p>有需要的加我微信 vx: abc123 领取全套教程福利！</p>
<script>tracker();</script>
<p>关注我的公众号获取更多推广内容。</p>
<p>总体来说，用 Python 做爬虫的体验很棒，值得学习。</p>
</div>
"""


def main() -> None:
    print("=" * 60)
    print("AI 内容清洗演示（provider 自动选择，缺模型则规则回退）")
    print("=" * 60)

    config = get_config()
    cleaner = ContentCleaner(config)
    print(f"\n当前 provider: {cleaner.provider.name}\n")

    print("[原始 HTML]")
    print(SAMPLE_HTML.strip())

    answer = Answer(
        answer_id="12345",
        question_title="Python 适合做爬虫吗？",
        author="张三",
        content_html=SAMPLE_HTML,
        voteup_count=128,
    )
    cleaner.clean_answer(answer)

    print("\n[清洗后 Markdown]（广告/引流/script 已剔除）")
    print(answer.content_markdown)
    print(f"\n[情感标签] {answer.sentiment}")
    print(f"[校验] {'通过' if answer.is_valid() else answer.validate()}")


if __name__ == "__main__":
    main()
