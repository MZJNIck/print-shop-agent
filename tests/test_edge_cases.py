"""边界用例：先钉住预期行为，再逐步实现。

标记说明：
  pytest.mark.xfail(reason=...) 表示"当前实现不满足，是已知缺陷"。
  实现后应移除标记，让测试转绿；转绿前它不会掩盖回归。
"""
from decimal import Decimal

import pytest

from printshop.agent import PrintShopAgent
from printshop.rules import normalize

AGENT = PrintShopAgent(use_llm=False)


# 1. 人名/文档名里出现"张"
def test_zhang_in_document_name_total():
    # "小张日记"不能被当成页数，但 10 页必须算对
    quote = AGENT.quote("帮我打印小张日记 10 页")
    assert quote.total == Decimal("5.00")


def test_zhang_in_document_name_group():
    quote = AGENT.quote("帮我打印小张日记 10 页")
    assert quote.order.groups[0].name == "小张日记"


# 2. "张三"：张在前、三在后，不应被量词规则命中
def test_zhang_san_not_broken():
    quote = AGENT.quote("打印张三的论文 80 页")
    assert quote.order.groups[0].name == "论文"
    assert quote.order.groups[0].source_pages == 80


# 3. 合成词"复印机"
def test_fuyinji_result_ok():
    quote = AGENT.quote("复印机坏了，帮我打印 15 页手册")
    assert quote.total == Decimal("7.50")


def test_fuyinji_text_not_rewritten():
    assert "打印机" not in normalize("复印机坏了")


# 4. 工艺修饰语"双面"不能变成 2 页
def test_double_sided_no_extra_charge():
    quote = AGENT.quote("双面打印，合同 10 页")
    assert quote.total == Decimal("5.00")


def test_double_sided_captured():
    quote = AGENT.quote("双面打印，合同 10 页")
    assert quote.order.groups[0].finish == "双面"


# 5. "第 3 张"是序数，不是 3 页，应澄清
def test_ordinal_zhang_needs_clarification():
    quote = AGENT.quote("第 3 张纸重打")
    assert quote.complete is False


# 6. 书名号里的内容应作为组名，不参与页数抽取
def test_book_title_group():
    quote = AGENT.quote("《第 3 页》文档打 2 份")
    assert quote.order.groups[0].name == "第 3 页"


# 7. "除了封面"是范围语义，应澄清而不是当唯一组
def test_except_cover_scope():
    quote = AGENT.quote("除了封面，其余都打两份")
    assert any(("范围" in item) or ("除" in item) for item in quote.questions)


# 8. 多文档各自册数
def test_multi_doc_books():
    quote = AGENT.quote("合同 10 页装 1 本，论文 80 页装 2 本")
    assert quote.total == Decimal("105.00")


# 9. 量词别名：张/每张
def test_zhang_each_copy():
    quote = AGENT.quote("20 张，每张 3 份")
    assert quote.order.groups[0].source_pages == 20
    assert quote.order.groups[0].copies == 3
    assert quote.total == Decimal("30.00")


# 10. 模糊数量"两三页"应澄清，不能取成 3 页
def test_ambiguous_quantity_clarification():
    quote = AGENT.quote("两三页的资料")
    assert quote.complete is False
