"""TG 频道解析器测试：用固定 HTML 片段，验证标题/作者/浏览/翻页解析。

重点回归：作者昵称以 emoji 开头时（渲染为 <i class="emoji" style="...url('...')">），
旧正则会因 url('...') 的右括号提前截断而抓到一堆 HTML —— 此处锁住修复。
"""
from zhihu_crawler.sources.tgchannel import TgChannelSource, _redact, _strip_tags


def _block(msg_id, topic_id, title, author_html, body="正文摘要内容", posts=3, views="12"):
    return f'''<div class="tgme_widget_message js-widget_message" data-post="linuxdoit/{msg_id}">
  <div class="tgme_widget_message_text" dir="auto"><b><u>{title}</u></b><br/><br/>{body}<br/><br/>{posts} 个帖子 - 2 位参与者<br/><br/><a href="https://linux.do/t/topic/{topic_id}" target="_blank">阅读完整话题</a><br/><br/>via <a href="https://linux.do/t/topic/{topic_id}">LINUX DO - 最新话题</a> (author: {author_html})</div>
  <span class="tgme_widget_message_views">{views}</span>
  <time datetime="2026-07-10T12:48:21+00:00"></time>
</div>'''


def test_parse_basic_fields():
    src = TgChannelSource()
    html = _block(350100, 2560690, "三星电子工会内部又吵开了", "拾雨", posts=5, views="20")
    parsed = list(src._parse_page(html))
    assert len(parsed) == 1
    it = parsed[0].item
    assert it.external_id == "2560690"
    assert it.title == "三星电子工会内部又吵开了"
    assert it.author == "拾雨"
    assert it.comment_count == 5
    assert it.score == 20
    assert it.url == "https://linux.do/t/topic/2560690"
    assert "tg_msg:350100" in it.tags


def test_author_with_emoji_prefix_not_polluted():
    # 作者昵称前带 emoji：TG 渲染成 <i class="emoji" style="background-image:url('//...png')">🛡</i>Name
    emoji_author = (
        '<i class="emoji" style="background-image:url(\'//telegram.org/img/emoji/40/F09F9BA1.png\')">'
        '\U0001f6e1</i>ShieldGuy'
    )
    src = TgChannelSource()
    html = _block(350101, 2560691, "一个话题", emoji_author)
    it = list(src._parse_page(html))[0].item
    # 关键：作者不应包含任何 HTML 残留 / url( / class=
    assert "<" not in it.author
    assert "url(" not in it.author
    assert "class=" not in it.author
    assert "ShieldGuy" in it.author


def test_non_topic_message_skipped():
    src = TgChannelSource()
    # 没有 linux.do/t/topic 链接的公告消息应被跳过
    html = ('<div class="tgme_widget_message" data-post="linuxdoit/1">'
            '<div class="tgme_widget_message_text"><b><u>公告</u></b>纯公告</div></div>')
    assert list(src._parse_page(html)) == []


def test_views_k_suffix():
    src = TgChannelSource()
    html = _block(350102, 2560692, "热帖", "someone", views="1.2K")
    it = list(src._parse_page(html))[0].item
    assert it.score == 1200


def test_redact_secrets():
    assert "[REDACTED]" in _redact("key: sk-abcdefghijklmnop1234567890")
    assert "[REDACTED]" in _redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")


def test_strip_tags_br_to_newline():
    assert _strip_tags("a<br/>b<br>c") == "a\nb\nc"
