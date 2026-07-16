"""解析器测试：API JSON + HTML 回退 + 去噪。"""
import json

from zhihu_crawler.parser import parse_search_api, parse_answer_html


def test_parse_search_api():
    payload = {
        "data": [
            {
                "object": {
                    "type": "answer",
                    "id": 111,
                    "content": "<p>内容A</p>",
                    "voteup_count": 50,
                    "comment_count": 3,
                    "author": {"name": "作者1"},
                    "question": {"name": "问题1"},
                    "url": "https://www.zhihu.com/answer/111",
                }
            }
        ]
    }
    answers = parse_search_api(json.dumps(payload))
    assert len(answers) == 1
    a = answers[0]
    assert a.answer_id == "111"
    assert a.question_title == "问题1"
    assert a.author == "作者1"
    assert a.voteup_count == 50


def test_parse_search_api_article_uses_title():
    """文章类型没有 question.name，标题应回退到 title 字段。"""
    payload = {"data": [{"object": {
        "type": "article", "id": 222, "title": "分布式爬虫小结",
        "content": "<p>正文</p>", "author": {"name": "作者"},
        "url": "https://zhuanlan.zhihu.com/p/222",
    }}]}
    answers = parse_search_api(json.dumps(payload))
    assert len(answers) == 1
    assert answers[0].question_title == "分布式爬虫小结"
    assert answers[0].is_valid()


def test_parse_html_strips_noise():
    """HTML 回退解析应去掉 script 等干扰节点。"""
    html = """
    <html><body>
      <h1 class="QuestionHeader-title">测试问题</h1>
      <div class="RichContent-inner">
        <p>正文内容</p>
        <script>evil()</script>
        <div style="display:none">干扰文本</div>
      </div>
    </body></html>
    """
    a = parse_answer_html(html, url="https://www.zhihu.com/question/1/answer/999")
    assert a is not None
    assert a.answer_id == "999"
    assert "正文内容" in a.content_html
    assert "evil" not in a.content_html
    assert "干扰文本" not in a.content_html


def test_parse_html_returns_none_on_garbage():
    assert parse_answer_html("<html></html>") is None
