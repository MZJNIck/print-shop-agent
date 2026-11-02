"""deepseek-flash 抽取层单测：不联网，用假响应验证解析链路。"""
import pytest

from printshop import llm


def test_to_order_normalizes_model_output():
    obj = {
        "groups": [
            {"name": "正文", "source_pages": 10, "copies": 2, "typeset": None},
            {"name": "封面", "source_pages": 1, "copies": 1, "typeset": True},
        ],
        "books": 2,
        "bind": True,
        "questions": [],
    }
    order = llm._to_order(obj, "x", "deepseek-flash")
    assert [g.name for g in order.groups] == ["正文", "封面"]
    assert order.groups[0].source_pages == 10
    assert order.groups[1].typeset is True
    assert order.books == 2
    assert order.parser == "deepseek-flash"


def test_loads_strips_markdown_fence():
    assert llm._loads('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_requires_api_key():
    with pytest.raises(llm.LLMError):
        llm.parse("帮我打印 3 页", api_key="")


def test_parse_with_mocked_transport(monkeypatch):
    fake = {
        "choices": [
            {
                "message": {
                    "content": '{"groups": [{"name": "合同", "source_pages": 10, '
                    '"copies": 1, "typeset": null}], "books": 1, "bind": true}'
                }
            }
        ]
    }
    monkeypatch.setattr(llm, "_post", lambda *args, **kwargs: fake)
    order = llm.parse("帮我打一份合同，一共 10 页，装订成 1 本", api_key="test-key")
    assert order.groups[0].name == "合同"
    assert order.books == 1
    assert order.parser == "deepseek-flash"


def test_retry_on_bad_format_then_success(monkeypatch):
    calls = {"n": 0}
    good = (
        '{"groups": [{"name": "合同", "source_pages": 10, "copies": 1, '
        '"typeset": null}], "books": 1, "bind": true}'
    )

    def fake(*args, **kwargs):
        calls["n"] += 1
        return {"choices": [{"message": {"content": "不是 JSON" if calls["n"] == 1 else good}}]}

    monkeypatch.setattr(llm, "_post", fake)
    order = llm.parse("帮我打一份合同，10 页，装订 1 本", api_key="test")
    assert order.groups[0].source_pages == 10
    assert order.llm_attempts == 2


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_post",
        lambda *args, **kwargs: {"choices": [{"message": {"content": "不是 JSON"}}]},
    )
    with pytest.raises(llm.LLMError):
        llm.parse("帮我打印 3 页", api_key="test", max_attempts=3)


def test_validate_output_rejects_missing_groups():
    problems = llm.validate_llm_output({"books": 1})
    assert any("groups" in item for item in problems)


def test_validate_output_accepts_well_formed():
    assert (
        llm.validate_llm_output(
            {"groups": [{"name": "合同", "source_pages": 10, "copies": 1}]}
        )
        == []
    )
