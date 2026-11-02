"""字段级合并测试：规则优先、缺字段用 LLM 补、冲突单独报。"""
from printshop.merge import merge_orders
from printshop.models import Group, Order


def test_fill_missing_pages_from_llm():
    rules_order = Order(groups=[Group("合同", 0, 1)])
    llm_order = Order(groups=[Group("合同", 10, 1)])
    merged, conflicts = merge_orders(rules_order, llm_order)
    assert merged.groups[0].source_pages == 10
    assert conflicts == []


def test_conflict_on_different_pages():
    rules_order = Order(groups=[Group("合同", 10, 1)])
    llm_order = Order(groups=[Group("合同", 12, 1)])
    merged, conflicts = merge_orders(rules_order, llm_order)
    assert "合同.source_pages" in conflicts


def test_group_set_conflict():
    rules_order = Order(groups=[Group("合同", 10, 1)])
    llm_order = Order(groups=[Group("论文", 10, 1)])
    merged, conflicts = merge_orders(rules_order, llm_order)
    assert "groups" in conflicts


def test_fill_books_from_llm():
    rules_order = Order(groups=[Group("合同", 10, 1)])
    llm_order = Order(groups=[Group("合同", 10, 1, books=1)])
    merged, conflicts = merge_orders(rules_order, llm_order)
    assert merged.groups[0].books == 1
