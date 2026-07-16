"""关键词匹配引擎测试。"""
from linuxdo_bot.matcher import match_any, _match


def test_plain_substring_case_insensitive():
    assert _match("python", "Learning PYTHON basics")
    assert not _match("rust", "python and go")


def test_and_semantics_space():
    assert _match("python django", "python + django tutorial")
    assert not _match("python django", "python only")


def test_or_semantics_pipe():
    assert _match("python|golang", "a golang post")
    assert _match("python|golang", "a python post")
    assert not _match("python|golang", "a rust post")


def test_combined_and_or():
    # (ai 或 llm) 且 agent
    assert _match("ai|llm agent", "building an LLM agent")
    assert _match("ai|llm agent", "an AI agent framework")
    assert not _match("ai|llm agent", "an AI chatbot")   # 缺 agent
    assert not _match("ai|llm agent", "a coding agent")  # 缺 ai/llm


def test_regex_mode():
    assert _match("/pytho[nz]/", "I use pythoz sometimes")
    assert _match("/v\\d+\\.\\d+/", "release v2.5 is out")
    assert not _match("/^start/", "not at start")


def test_bad_regex_no_crash():
    assert _match("/[/", "anything") is False


def test_match_any_across_texts():
    hits = match_any(["python", "rust", "ai|ml"], "Python tips", "some ML content")
    assert "python" in hits
    assert "ai|ml" in hits
    assert "rust" not in hits
