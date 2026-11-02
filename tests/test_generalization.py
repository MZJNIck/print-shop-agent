"""泛化用例：证明解析器不止能跑 5 条样例。"""
from decimal import Decimal

from printshop.agent import PrintShopAgent

AGENT = PrintShopAgent(use_llm=False)


def test_resume_five_copies_without_binding():
    q = AGENT.quote("简历 2 页打 5 份，不要装订")
    assert q.total == Decimal("5.00")
    assert q.order.groups[0].copies == 5
    assert q.order.bind is False


def test_report_typeset_and_bind():
    q = AGENT.quote("报告 50 页，要排版，装订成 3 本")
    # 排版 50×3=150 + 打印 50×0.5=25 + 装订 3×20=60
    assert q.total == Decimal("235.00")


def test_explicit_pages_missing_triggers_question():
    q = AGENT.quote("帮我打一份合同，装订成 1 本")
    assert q.complete is False
    assert any("页数" in item for item in q.questions)


def test_negation_of_binding_does_not_cancel_typeset():
    # "不需要装订"里的"不"不能把后面的"需要排版"判成不排版
    q = AGENT.quote("论文 80 页，不需要装订，需要排版")
    assert q.order.groups[0].typeset is True
    assert q.total == Decimal("280.00")
