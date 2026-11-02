"""LangGraph 编排层测试：图的结果必须与顺序调用完全一致。"""
import pytest

pytest.importorskip("langgraph")

from decimal import Decimal

from printshop import graph
from printshop.agent import PrintShopAgent
from printshop.cli import load_samples

EXPECTED = ["25.00", "70.00", "120.00", "7.50", "57.00"]


def test_graph_runs_all_samples():
    for text, expected in zip(load_samples(), EXPECTED):
        quote = graph.quote_with_graph(text, use_llm=False)
        assert quote.total == Decimal(expected), text
        assert quote.complete is True


def test_graph_matches_sequential_agent():
    agent = PrintShopAgent(use_llm=False)
    for text in load_samples():
        sequential = agent.quote(text)
        graphed = graph.quote_with_graph(text, use_llm=False)
        assert sequential.total == graphed.total
        assert [line.qty for line in sequential.lines] == [line.qty for line in graphed.lines]
        assert sequential.order.parser == graphed.order.parser


def test_graph_llm_failure_falls_back_to_rules(monkeypatch):
    from printshop import llm

    def boom(*args, **kwargs):
        raise llm.LLMError("boom")

    monkeypatch.setattr(llm, "parse", boom)
    quote = graph.quote_with_graph(
        "帮我打一份合同，一共 10 页，装订成 1 本", api_key="fake-key", use_llm=True
    )
    assert quote.order.parser == "rules(fallback)"
    assert quote.total == Decimal("25.00")
    assert any("回退" in item for item in quote.questions)


def test_graph_missing_pages_is_incomplete():
    quote = graph.quote_with_graph("帮我打一份合同，装订成 1 本", use_llm=False)
    assert quote.blocked is True
    assert quote.complete is False
    assert any("页" in item for item in quote.questions)


def test_graph_has_expected_nodes():
    compiled = graph.get_graph()
    nodes = set(compiled.get_graph().nodes)
    expected = {
        "ingest",
        "load_pricebook",
        "dual_parse",
        "compare",
        "llm_judge",
        "validate",
        "clarify",
        "price",
        "sum",
        "annotate",
        "render",
    }
    assert expected <= nodes
