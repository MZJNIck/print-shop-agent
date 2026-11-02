"""规则解析器单测：锁定 5 条规格样例的结构。"""
from printshop.rules import cn_to_int, parse_order


def test_cn_to_int():
    assert cn_to_int("十") == 10
    assert cn_to_int("二十") == 20
    assert cn_to_int("三十") == 30
    assert cn_to_int("一百") == 100
    assert cn_to_int("两") == 2
    assert cn_to_int("16") == 16


def test_case1_contract():
    order = parse_order("帮我打一份合同，一共 10 页，装订成 1 本")
    assert len(order.groups) == 1
    g = order.groups[0]
    assert (g.name, g.source_pages, g.copies, g.typeset) == ("合同", 10, 1, None)
    assert order.total_books == 1 and order.bind is True


def test_case2_ppt_three_copies_two_books():
    order = parse_order("PPT 共 20 页，每页打 3 份，装成 2 册")
    g = order.groups[0]
    assert (g.name, g.source_pages, g.copies) == ("PPT", 20, 3)
    assert order.total_books == 2


def test_case3_thesis_two_copies_two_books():
    order = parse_order("论文 80 页打两份，各装订一本")
    g = order.groups[0]
    assert (g.name, g.source_pages, g.copies) == ("论文", 80, 2)
    assert order.total_books == 2


def test_case4_print_only():
    order = parse_order("只要打印，不要装订：手册 15 页")
    assert order.total_books == 0 and order.bind is False
    g = order.groups[0]
    assert (g.name, g.source_pages, g.copies, g.typeset) == ("手册", 15, 1, False)


def test_case5_grouped_cover_toc_body():
    order = parse_order(
        "封面和目录各 1 页、正文 30 页，正文打 2 份，封面目录各打 1 份，装 1 本，封面目录也算要排版"
    )
    by_name = {g.name: g for g in order.groups}
    assert set(by_name) == {"封面", "目录", "正文"}
    assert (by_name["封面"].source_pages, by_name["封面"].copies) == (1, 1)
    assert (by_name["目录"].source_pages, by_name["目录"].copies) == (1, 1)
    assert (by_name["正文"].source_pages, by_name["正文"].copies) == (30, 2)
    assert by_name["封面"].typeset is True and by_name["目录"].typeset is True
    assert by_name["正文"].typeset is None
    assert order.total_books == 1


def test_unknown_document_falls_back_to_file_group():
    order = parse_order("帮我打印 3 页")
    assert len(order.groups) == 1
    assert order.groups[0].source_pages == 3
    assert order.total_books == 0


def test_synonym_quantifier_zhang():
    # "张"归一到"页"：非模型路径也能接住这个变体
    order = parse_order("PPT 20 张，每张 3 份")
    g = order.groups[0]
    assert (g.source_pages, g.copies) == (20, 3)


def test_synonym_quantifier_mian():
    order = parse_order("资料 10 面，打 2 份")
    assert order.groups[0].source_pages == 10

