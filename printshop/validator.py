"""槽位与范围校验：不猜，缺什么就报什么。

校验结果不直接改金额，只作为"澄清问题"进入报价单，
由 clarify 节点统一收集。这样"能算的照算，算不了的标出来"。
"""
from __future__ import annotations

from typing import List

from .models import Order

MAX_PAGES = 1000
MAX_COPIES = 100
MAX_BOOKS = 100


def detect_missing(order: Order) -> List[dict]:
    """返回缺失的槽位，用于"不聚合金额 + 澄清"。

    每条：{"slot": "pages|copies|books|groups|bind", "group": 组名, "message": 追问文案}
    """
    missing: List[dict] = []

    if not order.groups:
        missing.append({"slot": "groups", "group": None, "message": "要打印什么文档？请补充文档名。"})
        return missing

    for g in order.groups:
        if not g.source_pages or g.source_pages <= 0:
            missing.append(
                {"slot": "pages", "group": g.name, "message": "「%s」打印多少页？" % g.name}
            )
        if not g.copies or g.copies <= 0:
            missing.append(
                {"slot": "copies", "group": g.name, "message": "「%s」要打印几份？" % g.name}
            )

    if order.bind is False and (order.books > 0 or any(g.books for g in order.groups)):
        missing.append(
            {"slot": "bind", "group": None, "message": "你说了不要装订，但又提到册数，到底装不装订？"}
        )

    return missing


def detect_confirmations(order: Order) -> List[str]:
    """可继续计费、但需要用户确认的疑点（不阻塞报价）。"""
    confirmations: List[str] = []
    if order.bind is False or order.total_books <= 0:
        return confirmations

    copy_values = {g.copies for g in order.groups}
    if len(copy_values) != 1:
        return confirmations

    copies = next(iter(copy_values))
    if copies != order.total_books:
        confirmations.append(
            "份数 %d 与装订册数 %d 不匹配，是否继续按此计费？"
            "（如不认可，请按原格式重新输入）" % (copies, order.total_books)
        )
    return confirmations


def validate_order(order: Order) -> List[str]:
    """返回所有字段级问题；空列表表示可以报价。

    缺失槽位统一由 detect_missing 给出，这里只补范围/一致性检查，
    避免同一个缺失被报两遍。
    """
    issues: List[str] = [item["message"] for item in detect_missing(order)]

    for g in order.groups:
        if g.source_pages and g.source_pages > MAX_PAGES:
            issues.append("「%s」的页数 %d 超出上限 %d，请确认" % (g.name, g.source_pages, MAX_PAGES))
        if g.copies and g.copies > MAX_COPIES:
            issues.append("「%s」的份数 %d 超出上限 %d，请确认" % (g.name, g.copies, MAX_COPIES))
        if g.books is not None and not (0 <= g.books <= MAX_BOOKS):
            issues.append("「%s」的装订册数 %d 超出范围 0-%d" % (g.name, g.books, MAX_BOOKS))

    if not (0 <= order.books <= MAX_BOOKS):
        issues.append("装订册数 %d 超出范围 0-%d" % (order.books, MAX_BOOKS))

    return issues
