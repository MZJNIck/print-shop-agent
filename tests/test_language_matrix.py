"""语言矩阵：30 条不同类型的自然语言下单，覆盖规则层的全部已知边界。

全部离线（use_llm=False）执行，保证确定性；LLM 路径由 test_graph 覆盖。
"""
from decimal import Decimal

import pytest

from printshop import graph

pytest.importorskip("langgraph")

# (类型, 输入, 期望总价, 是否应 blocked)
CASES = [
    ("基础装订", "帮我打一份合同，一共 10 页，装订成 1 本", Decimal("25.00"), False),
    ("多份多册", "论文 80 页打两份，各装订一本", Decimal("120.00"), False),
    ("每页多份", "PPT 共 20 页，每页打 3 份，装成 2 册", Decimal("70.00"), False),
    ("否定装订", "只要打印，不要装订：手册 15 页", Decimal("7.50"), False),
    (
        "分组排版",
        "封面和目录各 1 页、正文 30 页，正文打 2 份，封面目录各打 1 份，装 1 本，封面目录也算要排版",
        Decimal("57.00"),
        False,
    ),
    ("量词张", "PPT 20 张，每张 3 份", Decimal("30.00"), False),
    ("量词面", "资料 10 面，打 2 份", Decimal("10.00"), False),
    ("文档名含张", "帮我打印小张日记 10 页", Decimal("5.00"), False),
    ("人名张三", "打印张三的论文 80 页", Decimal("40.00"), False),
    ("合成词复印机", "复印机坏了，帮我打印 15 页手册", Decimal("7.50"), False),
    ("书名号", "《第 3 页》文档打 2 份", Decimal("0"), True),
    ("序数", "第 3 张纸重打", Decimal("0"), True),
    ("模糊量", "两三页的资料", Decimal("0"), True),
    ("双面", "双面打印，合同 10 页", Decimal("5.00"), False),
    ("单面", "合同 10 页，单面打印", Decimal("5.00"), False),
    ("多文档各册", "合同 10 页装 1 本，论文 80 页装 2 本", Decimal("105.00"), False),
    ("范围语义", "除了封面，其余都打两份", Decimal("0"), True),
    ("缺页数", "帮我打一份合同", Decimal("0"), True),
    ("排版装订", "论文 80 页，要排版，打两份，各装订一本", Decimal("360.00"), False),
    ("简历多份", "帮我打一份简历，两页，打五份", Decimal("5.00"), False),
    ("倒装", "装订成 2 本，论文 80 页，打两份", Decimal("120.00"), False),
    ("数字后置", "打印 3 份，10 页的资料", Decimal("15.00"), False),
    ("中文数字复印", "二十页的报告，复印两份，装订两本", Decimal("60.00"), False),
    ("只打印不装订", "手册 15 页，只打印，不装订", Decimal("7.50"), False),
    ("两本册数", "合同 10 页，装订成两本", Decimal("45.00"), False),
    ("显式不排版", "论文 80 页，不要排版，打两份，装订两本", Decimal("120.00"), False),
    ("无文档名", "帮我打印 3 页", Decimal("1.50"), False),
    ("无意义输入", "今天天气不错", Decimal("0"), True),
    ("超范围", "合同 5000 页", Decimal("0"), True),
    ("澄清后拼接", "帮我打一份合同，10 页，2 份", Decimal("10.00"), False),
]


@pytest.mark.parametrize("kind,text,expected_total,expected_blocked", CASES)
def test_language_matrix(kind, text, expected_total, expected_blocked):
    quote = graph.quote_with_graph(text, use_llm=False, log_path=False)
    assert quote.blocked is expected_blocked, (kind, text)
    if not expected_blocked:
        assert quote.total == expected_total, (kind, text, quote.total)


def test_matrix_group_names():
    assert graph.quote_with_graph("帮我打印小张日记 10 页", use_llm=False, log_path=False).order.groups[0].name == "小张日记"
    assert graph.quote_with_graph("打印张三的论文 80 页", use_llm=False, log_path=False).order.groups[0].name == "论文"
    assert graph.quote_with_graph("《第 3 页》文档打 2 份", use_llm=False, log_path=False).order.groups[0].name == "第 3 页"


def test_matrix_finish():
    assert (
        graph.quote_with_graph("双面打印，合同 10 页", use_llm=False, log_path=False).order.groups[0].finish
        == "双面"
    )
    assert (
        graph.quote_with_graph("合同 10 页，单面打印", use_llm=False, log_path=False).order.groups[0].finish
        == "单面"
    )
