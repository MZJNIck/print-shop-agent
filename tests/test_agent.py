"""端到端单测：自然语言 -> 报价单，以及 JSON/Markdown 交付格式。"""
from decimal import Decimal

from printshop.agent import PrintShopAgent
from printshop.cli import load_samples
from printshop.render import to_json, to_markdown

# 口径 A：文档说"需要排版的原始页面才收费"，未提排版 -> 不排版
EXPECTED_NONE = ["25.00", "70.00", "120.00", "7.50", "57.00"]

# 口径 B：未提排版 -> 默认全文排版（便于对照另一种评测口径）
EXPECTED_ALL = ["55.00", "130.00", "360.00", "7.50", "147.00"]


def make_agent(**kwargs):
    kwargs.setdefault("use_llm", False)
    return PrintShopAgent(**kwargs)


def test_samples_default_typeset_off():
    agent = make_agent()
    for text, expected in zip(load_samples(), EXPECTED_NONE):
        quote = agent.quote(text)
        assert quote.total == Decimal(expected), (text, quote.total)
        assert quote.pricing_version == "2026-10-30"
        assert quote.complete is True


def test_samples_typeset_all():
    agent = make_agent(typeset_default="all")
    for text, expected in zip(load_samples(), EXPECTED_ALL):
        assert agent.quote(text).total == Decimal(expected), text


def test_without_api_key_falls_back_to_rules():
    agent = PrintShopAgent(api_key="", use_llm=True)
    quote = agent.quote("帮我打一份合同，一共 10 页，装订成 1 本")
    assert quote.order.parser == "rules(no api key)"
    assert quote.total == Decimal("25.00")


def test_quote_json_is_reconcilable():
    agent = make_agent()
    data = to_json(agent.quote(load_samples()[4]))
    assert data["pricing_version"] == "2026-10-30"
    assert [item["item"] for item in data["line_items"]] == ["排版费", "打印费", "装订费"]
    subtotal_sum = sum(Decimal(item["subtotal"]) for item in data["line_items"])
    assert subtotal_sum == Decimal(data["total"]) == Decimal("57.00")
    assert data["print_breakdown"][2]["print_pages"] == 60


def test_markdown_has_version_and_total():
    agent = make_agent()
    md = to_markdown(agent.quote("论文 80 页打两份，各装订一本"))
    assert "价目版本 2026-10-30" in md
    assert "合计：120.00 元" in md
    assert "打印费" in md and "装订费" in md


def test_multi_quote_json_is_valid_array():
    """--json 批量输出必须是合法 JSON 数组，方便脚本消费。"""
    import contextlib
    import io
    import json

    from printshop.cli import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--demo", "--json"])
    data = json.loads(buf.getvalue())
    assert isinstance(data, list) and len(data) == 5
    assert [item["total"] for item in data] == EXPECTED_NONE
