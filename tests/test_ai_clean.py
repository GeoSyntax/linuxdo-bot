"""AI 清洗（规则模式）测试。"""
from zhihu_crawler.ai.providers import RuleProvider
from zhihu_crawler.ai.cleaner import ContentCleaner
from zhihu_crawler.config import Config
from zhihu_crawler.models import Answer

HTML = (
    "<div><p>这个方案很好，推荐使用。</p>"
    "<p>加微信 vx123 领福利！</p>"
    "<script>x()</script>"
    "<p>关注公众号获取推广。</p></div>"
)


def _cleaner():
    cfg = Config()
    cfg.ai.provider = "rule"
    return ContentCleaner(cfg)


def test_rule_provider_strips_html_and_ads():
    c = _cleaner()
    md, sentiment = c.clean_text(HTML)
    assert "<" not in md               # 标签清掉
    assert "微信" not in md            # 广告段剔除
    assert "公众号" not in md
    assert "推荐使用" in md            # 正文保留


def test_rule_provider_removes_script_content():
    """script/style 的内容也要删掉，不能残留在正文。"""
    c = _cleaner()
    md, _ = c.clean_text("<p>正文</p><script>tracker();alert(1)</script>")
    assert "tracker" not in md
    assert "alert" not in md
    assert "正文" in md


def test_rule_provider_removes_verbose_wechat_ad():
    """『加我微信 vx: abc123』这类变体也要能剔除。"""
    c = _cleaner()
    md, _ = c.clean_text("<p>有用的正文</p><p>加我微信 vx: abc123 领取全套教程福利</p>")
    assert "abc123" not in md
    assert "有用的正文" in md


def test_rule_sentiment_positive():
    c = _cleaner()
    _, sentiment = c.clean_text("<p>非常好，很喜欢，强烈推荐</p>")
    assert sentiment == "positive"


def test_rule_sentiment_negative():
    c = _cleaner()
    _, sentiment = c.clean_text("<p>太差了，垃圾，很失望</p>")
    assert sentiment == "negative"


def test_clean_answer_sets_flags():
    c = _cleaner()
    a = Answer(answer_id="1", question_title="Q", author="A", content_html=HTML)
    c.clean_answer(a)
    assert a.is_cleaned is True
    assert a.content_markdown
    assert a.sentiment in ("positive", "neutral", "negative")


def test_provider_fallback_on_unavailable_ollama():
    """provider=ollama 但服务不可用时应降级为 rule。"""
    cfg = Config()
    cfg.ai.provider = "ollama"
    cfg.ai.ollama = {"host": "http://127.0.0.1:59999", "model": "none"}
    from zhihu_crawler.ai.providers import get_provider
    p = get_provider(cfg)
    assert isinstance(p, RuleProvider)
