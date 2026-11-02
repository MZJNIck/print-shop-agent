"""确定性计价引擎：输入 Order，输出可逐项核对的 Quote。

这里绝不调用 LLM。价格来自 pricing.yaml（带版本号），换价目只换文件，
报价单上会原样回显价目版本。

为了让 LangGraph 的节点"一个节点只做一件事"，这里把计价拆成四个可组合函数：

    compute_quantities  ->  PriceBook.build_lines  ->  sum_total  ->  PriceBook.collect_notes

PriceBook.quote 只是这四个函数的组合，对外行为完全不变。
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Order, Quote, QuoteLine
from .validator import detect_confirmations

CENT = Decimal("0.01")

DEFAULT_PRICING = Path(__file__).resolve().parent.parent / "pricing.yaml"

ITEM_KEYS = ("typeset", "print", "bind")


def _load_file(path: Path) -> dict:
    """按扩展名读取价目：.yaml/.yml 用 PyYAML，其余按 JSON（兼容旧文件）。"""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - 只在缺依赖时触发
            raise RuntimeError("读取 YAML 价目需要 PyYAML：uv pip install pyyaml") from exc
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError("价目 YAML 顶层必须是映射（key: value）")
        return data
    return json.loads(text)


def money(value) -> Decimal:
    """统一到分，四舍五入（ROUND_HALF_UP，避免银行家舍入）。"""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def validate_typeset_default(typeset_default: str) -> None:
    if typeset_default not in ("none", "all"):
        raise ValueError("typeset_default 只能是 'none' 或 'all'")


def compute_quantities(order: Order, typeset_default: str = "none") -> Dict[str, int]:
    """数出三个计费量：需排版源页（去重）、实际打印页、装订册数。"""
    validate_typeset_default(typeset_default)
    use_all = typeset_default == "all"

    def is_typeset(group) -> bool:
        return use_all if group.typeset is None else bool(group.typeset)

    bind_qty = 0 if order.bind is False else order.total_books

    return {
        "typeset": sum(g.source_pages for g in order.groups if is_typeset(g)),
        "print": order.total_print_pages,
        "bind": bind_qty,
    }


def sum_total(lines: List[QuoteLine]) -> Decimal:
    """把三行小计相加，得到总价。"""
    return money(sum((line.subtotal for line in lines), Decimal("0")))


class PriceBook:
    """一份价目表（含版本号）。"""

    def __init__(self, version: str, currency: str, items: Dict[str, dict]):
        self.version = version
        self.currency = currency
        self.items = items

    @classmethod
    def load(cls, path: Optional[str] = None) -> "PriceBook":
        p = Path(path) if path else DEFAULT_PRICING
        data = _load_file(p)
        return cls(
            version=str(data["version"]),
            currency=str(data.get("currency", "CNY")),
            items=data["items"],
        )

    def unit_price(self, key: str) -> Decimal:
        return money(self.items[key]["unit_price"])

    def build_lines(self, quantities: Dict[str, int]) -> List[QuoteLine]:
        """三个量 × 单价 -> 三行明细（基数 / 单价 / 小计）。"""
        lines: List[QuoteLine] = []
        for key in ITEM_KEYS:
            qty = int(quantities[key])
            item = self.items[key]
            unit_price = self.unit_price(key)
            subtotal = money(Decimal(qty) * unit_price)
            lines.append(
                QuoteLine(
                    key=key,
                    label=item["label"],
                    basis=item["basis"],
                    qty=qty,
                    unit_price=unit_price,
                    subtotal=subtotal,
                )
            )
        return lines

    def collect_notes(
        self, order: Order, quantities: Dict[str, int], typeset_default: str = "none"
    ) -> Tuple[List[str], List[str]]:
        """生成报价单上的"假设"和"待确认"，它们不参与金额。"""
        validate_typeset_default(typeset_default)
        use_all = typeset_default == "all"

        assumptions: List[str] = []
        total_books = quantities["bind"]
        if any(g.typeset is None for g in order.groups):
            assumptions.append(
                "未明确说明是否排版的内容，按「%s」计费"
                % ("默认需要排版" if use_all else "默认不排版")
            )
        if order.bind is False:
            assumptions.append("用户明确不要装订，装订费按 0 计")
        elif total_books == 0:
            assumptions.append("未说明装订，按不装订计费")
        if total_books > 0 and order.bind is not False:
            assumptions.append("装订费按册计，与每册页数无关")
            # 份数与册数不一致时主动暴露，而不是悄悄替用户决定装几本
            copy_values = {g.copies for g in order.groups}
            if len(copy_values) == 1:
                copies = next(iter(copy_values))
                if copies != total_books:
                    assumptions.append(
                        "打印份数 %d 与装订册数 %d 不一致：按字面分别计费；"
                        "若只装订部分份数或每份各装一册，请补充说明"
                        % (copies, total_books)
                    )

        questions: List[str] = []
        if not order.groups:
            questions.append("没有识别到要打印的内容，请补充文档名称、页数与份数")
        for g in order.groups:
            if g.source_pages <= 0:
                questions.append("「%s」的页数没有给出，请补充" % g.name)
            if g.copies <= 0:
                questions.append("「%s」的份数无效，请补充" % g.name)
        if order.books < 0:
            questions.append("装订册数不能为负数")

        for warning in order.warnings:
            questions.append(warning)

        return assumptions, questions

    def quote(self, order: Order, typeset_default: str = "none") -> Quote:
        """顺序组合四个步骤，等价于没有 LangGraph 时的执行路径。"""
        quantities = compute_quantities(order, typeset_default)
        lines = self.build_lines(quantities)
        total = sum_total(lines)
        assumptions, questions = self.collect_notes(order, quantities, typeset_default)

        return Quote(
            pricing_version=self.version,
            currency=self.currency,
            order=order,
            lines=lines,
            total=total,
            typeset_default=typeset_default,
            assumptions=assumptions,
            questions=questions,
            confirmations=detect_confirmations(order),
        )
