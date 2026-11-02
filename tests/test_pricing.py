"""计价引擎单测：不经过任何自然语言解析，直接喂 Order。"""
from decimal import Decimal

from printshop.models import Group, Order
from printshop.pricing import PriceBook

BOOK = PriceBook.load()


def quote(groups, books=0, bind=None, typeset_default="none"):
    order = Order(groups=groups, books=books, bind=bind)
    return BOOK.quote(order, typeset_default)


def test_pricebook_version_and_prices():
    assert BOOK.version == "2026-10-30"
    assert BOOK.unit_price("typeset") == Decimal("3.00")
    assert BOOK.unit_price("print") == Decimal("0.50")
    assert BOOK.unit_price("bind") == Decimal("20.00")


def test_contract_without_typeset():
    q = quote([Group("合同", 10, 1, None)], books=1)
    assert q.total == Decimal("25.00")
    assert [line.qty for line in q.lines] == [0, 10, 1]
    assert [line.subtotal for line in q.lines] == [
        Decimal("0.00"),
        Decimal("5.00"),
        Decimal("20.00"),
    ]


def test_typeset_charged_once_per_source_page():
    # 同一组打 3 份，排版费只按源页收一次
    q = quote([Group("正文", 30, 3, True)], books=3)
    assert q.total == Decimal("90.00") + Decimal("45.00") + Decimal("60.00")
    assert q.lines[0].qty == 30


def test_all_typeset_default():
    q = quote([Group("论文", 80, 2, None)], books=2, typeset_default="all")
    assert q.total == Decimal("360.00")


def test_explicit_no_typeset_beats_default_all():
    q = quote([Group("手册", 15, 1, False)], books=0, typeset_default="all")
    assert q.total == Decimal("7.50")


def test_bind_false_ignores_books():
    q = quote([Group("资料", 20, 1, None)], books=3, bind=False)
    assert q.lines[2].qty == 0


def test_fractional_total_is_exact():
    # 15 页 × 0.5 元 = 7.5 元，Decimal 不能出现浮点误差
    q = quote([Group("手册", 15, 1, None)])
    assert q.total == Decimal("7.50")
    assert str(q.total) == "7.50"


def test_missing_pages_produces_question_not_crash():
    q = quote([Group("简历", 0, 1, None)])
    assert q.complete is False
    assert "简历" in q.questions[0]


def test_assumption_when_typeset_unspecified():
    q = quote([Group("合同", 10, 1, None)])
    assert any("排版" in a for a in q.assumptions)


def test_copies_books_conflict_is_surfaced():
    # 样例 2：3 份却装 2 册，必须主动提示，而不是悄悄替用户决定
    q = quote([Group("PPT", 20, 3, None)], books=2)
    assert any("份数" in a and "册数" in a for a in q.assumptions)


def test_mixed_group_copies_do_not_warn():
    # 封面 1 份、正文 2 份、装 1 本 是正常的分组装订，不该误报
    q = quote(
        [Group("封面", 1, 1, True), Group("目录", 1, 1, True), Group("正文", 30, 2, None)],
        books=1,
    )
    assert not any("不一致" in a for a in q.assumptions)


def test_pricebook_loads_yaml_by_suffix(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text(
        'version: "2099-01-01"\n'
        "currency: CNY\n"
        "items:\n"
        "  typeset: {label: 排版费, basis: 源页面, unit_price: '1.00'}\n"
        "  print: {label: 打印费, basis: 实际打印页, unit_price: '2.00'}\n"
        "  bind: {label: 装订费, basis: 册, unit_price: '3.00'}\n",
        encoding="utf-8",
    )
    book = PriceBook.load(str(path))
    assert book.version == "2099-01-01"
    assert book.unit_price("print") == Decimal("2.00")

