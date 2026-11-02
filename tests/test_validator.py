"""槽位/范围校验测试：不猜，缺什么报什么。"""
from printshop.models import Group, Order
from printshop.validator import validate_order


def test_valid_order_has_no_issues():
    assert validate_order(Order(groups=[Group("合同", 10, 1)])) == []


def test_missing_pages():
    issues = validate_order(Order(groups=[Group("合同", 0, 1)]))
    assert any("页" in item for item in issues)


def test_pages_over_limit():
    issues = validate_order(Order(groups=[Group("合同", 5000, 1)]))
    assert any("上限" in item for item in issues)


def test_bind_false_but_books_present():
    issues = validate_order(Order(groups=[Group("合同", 10, 1)], books=2, bind=False))
    assert any("不要装订" in item for item in issues)
