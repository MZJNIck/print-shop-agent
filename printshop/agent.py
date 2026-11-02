"""对外入口：PrintShopAgent = LLM 抽取（可无 key 回退） + 确定性计价。"""
from __future__ import annotations

import os
from typing import Optional

from . import llm, rules
from .models import Order, Quote
from .pricing import PriceBook

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class PrintShopAgent:
    def __init__(
        self,
        pricing_path: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        typeset_default: str = "none",
        use_llm: bool = True,
        timeout: int = 45,
    ):
        self.pricebook = PriceBook.load(pricing_path)
        self.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.typeset_default = typeset_default
        self.use_llm = use_llm
        self.timeout = timeout

    @property
    def llm_ready(self) -> bool:
        return bool(self.use_llm and self.api_key and self.api_key.strip())

    def parse(self, text: str) -> Order:
        """自然语言 -> 订单。优先 deepseek-flash，失败/无 key 回退规则解析。"""
        if self.llm_ready:
            try:
                return llm.parse(
                    text,
                    api_key=self.api_key,
                    model=self.model,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
            except Exception as exc:  # noqa: BLE001 - 任何 LLM 异常都应降级，而不是让下单失败
                order = rules.parse_order(text)
                order.parser = "rules(fallback)"
                order.warnings.append("deepseek-flash 解析失败，已回退规则解析：%s" % exc)
                return order

        order = rules.parse_order(text)
        order.parser = "rules(no api key)" if self.use_llm else "rules"
        return order

    def quote(self, text: str) -> Quote:
        order = self.parse(text)
        return self.pricebook.quote(order, self.typeset_default)
