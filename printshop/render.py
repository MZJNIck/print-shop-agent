"""报价单渲染：同一份 Quote 输出为人读的 Markdown 与机器读的 JSON。"""
from __future__ import annotations

from typing import List

from .models import Quote


def fmt(value) -> str:
    return f"{value:.2f}"


def to_json(quote: Quote) -> dict:
    order = quote.order
    return {
        "pricing_version": quote.pricing_version,
        "currency": quote.currency,
        "parser": order.parser,
        "input": order.raw,
        "typeset_default": quote.typeset_default,
        "order": {
            "groups": [g.as_dict() for g in order.groups],
            "books": order.total_books,
            "bind": order.bind,
            "total_source_pages": order.total_source_pages,
            "total_print_pages": order.total_print_pages,
        },
        "line_items": [
            {
                "item": line.label,
                "basis": line.basis,
                "qty": line.qty,
                "unit_price": fmt(line.unit_price),
                "subtotal": fmt(line.subtotal),
            }
            for line in quote.lines
        ],
        "print_breakdown": [
            {
                "group": g.name,
                "source_pages": g.source_pages,
                "copies": g.copies,
                "print_pages": g.source_pages * g.copies,
            }
            for g in order.groups
        ],
        "total": fmt(quote.total),
        "assumptions": quote.assumptions,
        "questions": quote.questions,
        "confirmations": quote.confirmations,
        "complete": quote.complete,
        "blocked": quote.blocked,
    }


RETRY_TEMPLATE = """请按以下格式重新输入：
  文档名 + 页数 + 打印份数 + [装订册数] + [是否排版]
示例：
  合同 10 页，打印 2 份，装订 1 本，要排版"""


def render_error(questions: List[str], raw_text: str = "") -> str:
    """槽位不全时的异常卡：不聚合金额，只给缺失项和重输格式。"""
    out: List[str] = ["【无法报价】缺少必要信息，暂不聚合金额：", ""]
    for item in questions:
        out.append("- %s" % item)
    out.append("")
    out.append(RETRY_TEMPLATE)
    if raw_text:
        out.append("")
        out.append("你刚才输入：%s" % raw_text)
    return "\n".join(out)


def to_markdown(quote: Quote) -> str:
    if quote.blocked:
        return render_error(quote.questions, quote.order.raw)

    order = quote.order
    out: List[str] = []
    out.append("## 报价单（价目版本 %s）" % quote.pricing_version)
    out.append("")
    out.append("| 项目 | 计费基数 | 数量 | 单价（元） | 小计（元） |")
    out.append("|---|---|---:|---:|---:|")
    for line in quote.lines:
        out.append(
            "| %s | %s | %d | %s | %s |"
            % (line.label, line.basis, line.qty, fmt(line.unit_price), fmt(line.subtotal))
        )
    out.append("")
    out.append("**合计：%s 元**" % fmt(quote.total))
    out.append("")

    if order.groups:
        out.append("### 打印明细")
        for g in order.groups:
            pages = g.source_pages * g.copies
            out.append(
                "- %s：%d 页 × %d 份 = %d 打印页%s"
                % (g.name, g.source_pages, g.copies, pages, "（含排版）" if g.typeset else "")
            )
        out.append("")

    if quote.assumptions:
        out.append("### 计费假设")
        for item in quote.assumptions:
            out.append("- %s" % item)
        out.append("")

    if quote.confirmations:
        out.append("### 请确认")
        for item in quote.confirmations:
            out.append("- %s" % item)
        out.append("")

    if quote.questions:
        out.append("### 待确认")
        for item in quote.questions:
            out.append("- %s" % item)
        out.append("")
        out.append("> 报价不完整：以上信息确认后才可下单。")
        out.append("")

    out.append("_解析器：%s_" % order.parser)
    return "\n".join(out)
