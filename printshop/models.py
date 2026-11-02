"""数据模型：订单（Order）与报价单（Quote）。

设计原则：订单是"人话抽取"的产物，报价单是"代码计算"的产物，
两者都只含数据，不含任何 LLM 调用，方便单测与复算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional


@dataclass
class Group:
    """订单中的一个内容分组，例如封面 / 目录 / 正文 / 合同。

    typeset 采用三态：
      None  -> 用户没提排版，由全局口径（--typeset-default）决定
      True  -> 用户明确要求排版
      False -> 用户明确要求不排版（例如"只要打印"）
    """

    name: str
    source_pages: int = 0          # 源页数（排版按它计费）
    copies: int = 1                # 打印份数（打印页 = 源页 × 份数）
    typeset: Optional[bool] = None
    finish: Optional[str] = None   # 工艺：双面 / 单面；None 表示没提
    books: Optional[int] = None    # 该文档装订几本；None 表示没单独指定

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "source_pages": self.source_pages,
            "copies": self.copies,
            "typeset": self.typeset,
            "finish": self.finish,
            "books": self.books,
        }


@dataclass
class Order:
    groups: List[Group] = field(default_factory=list)
    books: int = 0                 # 装订册数
    bind: Optional[bool] = None    # 是否装订；None 表示没提
    raw: str = ""                  # 原始输入
    parser: str = "rules"          # 解析来源：rules / deepseek-flash / llm-judge
    llm_attempts: int = 0          # LLM 实际调用次数（含格式重试）
    warnings: List[str] = field(default_factory=list)

    @property
    def total_books(self) -> int:
        """有效装订册数：优先各组册数之和，否则全局册数。"""
        per_group = sum(g.books for g in self.groups if g.books is not None)
        return per_group if per_group > 0 else self.books

    @property
    def total_source_pages(self) -> int:
        return sum(g.source_pages for g in self.groups)

    @property
    def total_print_pages(self) -> int:
        return sum(g.source_pages * g.copies for g in self.groups)


@dataclass
class QuoteLine:
    key: str
    label: str
    basis: str
    qty: int
    unit_price: Decimal
    subtotal: Decimal


@dataclass
class Quote:
    pricing_version: str
    currency: str
    order: Order
    lines: List[QuoteLine]
    total: Decimal
    typeset_default: str
    assumptions: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    confirmations: List[str] = field(default_factory=list)  # 需用户确认但可继续计费
    blocked: bool = False  # True 表示槽位不全、未聚合金额

    @property
    def complete(self) -> bool:
        """槽位齐全且未阻塞时为 True。"""
        return not self.blocked and not self.questions
