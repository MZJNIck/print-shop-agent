"""双跑结果的字段级合并。

原则：
  * 规则版（primary）优先：可解释、可测；
  * 规则缺失的字段，用 LLM 版（secondary）补；
  * 两边都有值但不同，记一条冲突，交给 LLM 二次校验；
  * 合并只补字段，不作废整单。
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Tuple

from .models import Group, Order

_FIELDS = ("source_pages", "copies", "typeset", "finish", "books")
_NUMERIC = {"source_pages", "copies", "books"}


def _missing(field: str, value) -> bool:
    if value is None:
        return True
    if field in _NUMERIC and value == 0:
        return True
    return False


def _merge_group(ga: Group, gb: Group) -> Tuple[Group, List[str]]:
    merged = replace(ga)
    conflicts: List[str] = []
    for field in _FIELDS:
        va, vb = getattr(ga, field), getattr(gb, field)
        if _missing(field, va) and not _missing(field, vb):
            setattr(merged, field, vb)
        elif not _missing(field, va) and not _missing(field, vb) and va != vb:
            conflicts.append("%s.%s" % (ga.name, field))
    return merged, conflicts


def merge_orders(primary: Order, secondary: Order) -> Tuple[Order, List[str]]:
    """返回 (合并后的订单, 冲突字段列表)。"""
    a = {g.name: g for g in primary.groups}
    b = {g.name: g for g in secondary.groups}
    conflicts: List[str] = []

    if set(a) != set(b):
        conflicts.append("groups")

    groups: List[Group] = []
    for name, ga in a.items():
        gb = b.get(name)
        if gb is None:
            groups.append(replace(ga))
            continue
        merged, group_conflicts = _merge_group(ga, gb)
        groups.append(merged)
        conflicts.extend(group_conflicts)

    for name, gb in b.items():
        if name not in a:
            groups.append(replace(gb))

    books = primary.books
    if books == 0 and secondary.books > 0:
        books = secondary.books
    elif books > 0 and secondary.books > 0 and books != secondary.books:
        conflicts.append("books")

    bind = primary.bind if primary.bind is not None else secondary.bind

    merged_order = Order(
        groups=groups,
        books=books,
        bind=bind,
        raw=primary.raw,
        parser="merged",
    )
    return merged_order, conflicts
