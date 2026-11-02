"""份数与装订册数不一致时的确认规则。"""
from decimal import Decimal

import pytest

from printshop import graph
from printshop.models import Group, Order
from printshop.pricing import PriceBook

pytest.importorskip("langgraph")


def test_confirm_when_copies_books_mismatch():
    # 样例 2：3 份装 2 册，可继续计费，但必须请用户确认
    quote = graph.quote_with_graph(
        "PPT 共 20 页，每页打 3 份，装成 2 册", use_llm=False, log_path=False
    )
    assert quote.blocked is False
    assert quote.total == Decimal("70.00")
    assert any("不匹配" in item for item in quote.confirmations)
    assert any("是否继续按此计费" in item for item in quote.confirmations)


def test_no_confirm_when_copies_match():
    quote = graph.quote_with_graph(
        "论文 80 页打两份，各装订一本", use_llm=False, log_path=False
    )
    assert quote.confirmations == []


def test_pricing_quote_carries_confirmations():
    book = PriceBook.load()
    quote = book.quote(Order(groups=[Group("PPT", 20, 3)], books=2))
    assert any("不匹配" in item for item in quote.confirmations)
