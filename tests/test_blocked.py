"""槽位不全：不聚合金额、给重输格式、写决策日志。"""
import json
from decimal import Decimal

import pytest

from printshop import graph

pytest.importorskip("langgraph")


def test_blocked_quote_has_no_amount():
    quote = graph.quote_with_graph("帮我打一份合同", use_llm=False, log_path=False)
    assert quote.blocked is True
    assert quote.total == Decimal("0")
    assert quote.lines == []
    assert quote.complete is False


def test_blocked_output_has_retry_template():
    result = graph.invoke_graph("帮我打一份合同", use_llm=False, log_path=False)
    output = result["output"]
    assert "无法报价" in output
    assert "重新输入" in output
    assert "打印多少页" in output


def test_decision_log_written(tmp_path):
    log_file = tmp_path / "decisions.jsonl"
    graph.invoke_graph("帮我打一份合同", use_llm=False, log_path=str(log_file))
    assert log_file.exists()
    record = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["blocked"] is True
    assert record["input"] == "帮我打一份合同"
    assert record["issues"]


def test_complete_quote_is_not_blocked():
    quote = graph.quote_with_graph(
        "帮我打一份合同，一共 10 页，装订成 1 本", use_llm=False, log_path=False
    )
    assert quote.blocked is False
    assert quote.complete is True
    assert quote.total == Decimal("25.00")
