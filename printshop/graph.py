"""LangGraph 编排层：双跑 + 字段级合并 + 二次校验 + 槽位校验 + 澄清。

    START
      -> ingest             读原话
      -> load_pricebook     读价目表
      -> dual_parse         非模型规则解析 + LLM 解析（双跑）
      -> compare            字段级合并：一致/无冲突 -> validate
      -> llm_judge          有冲突时让 LLM 二次校验（裁判/修正）
      -> validate           槽位、范围、一致性校验
      -> clarify            缺字段 -> 收集问题（不猜）
      -> price -> sum -> annotate -> render -> END

没有安装 langgraph 时，本模块 import 失败，CLI 会自动回退到 agent.quote()。
"""
from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import llm, rules
from .decision_log import log_decision
from .merge import merge_orders
from .pricing import PriceBook, compute_quantities, sum_total
from .render import to_json, to_markdown
from .validator import detect_confirmations, detect_missing, validate_order

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class QuoteState(TypedDict, total=False):
    # 输入
    raw_text: str
    pricing_path: Optional[str]
    typeset_default: str
    use_llm: bool
    api_key: str
    model: str
    base_url: str
    output_mode: str  # "markdown" | "json"

    # 双跑与仲裁
    rules_order: Any
    llm_order: Any
    order: Any
    conflicts: List[str]
    issues: List[str]
    missing: List[Any]
    blocked: bool
    log_path: Any
    judge_choice: str
    judge_confidence: float
    judge_error: str
    parser: str

    # 计价与输出
    price_book: Any
    quantities: Dict[str, int]
    lines: List[Any]
    total: Any
    assumptions: List[str]
    questions: List[str]
    quote: Any
    output: str


def ingest(state: QuoteState) -> Dict[str, Any]:
    """节点 1：校验并规范化用户原话。"""
    text = (state.get("raw_text") or "").strip()
    if not text:
        raise ValueError("下单内容为空")
    return {"raw_text": text}


def load_pricebook(state: QuoteState) -> Dict[str, Any]:
    """节点 2：加载价目表，得到三个单价和价目版本。"""
    return {"price_book": PriceBook.load(state.get("pricing_path"))}


def _llm_ready(state: QuoteState) -> bool:
    return bool(state.get("use_llm", True) and (state.get("api_key") or "").strip())


def dual_parse(state: QuoteState) -> Dict[str, Any]:
    """节点 3：双跑。非模型规则解析 + LLM 解析，互不覆盖，交给 compare 合并。"""
    text = state["raw_text"]
    rules_order = rules.parse_order(text)

    llm_order = None
    if _llm_ready(state):
        try:
            llm_order = llm.parse(
                text,
                api_key=state["api_key"],
                model=state.get("model") or DEFAULT_MODEL,
                base_url=state.get("base_url") or DEFAULT_BASE_URL,
            )
        except Exception as exc:  # noqa: BLE001 - LLM 失败要能降级
            rules_order.parser = "rules(fallback)"
            rules_order.warnings.append(
                "deepseek-flash 解析失败，已回退规则解析：%s" % exc
            )
    else:
        rules_order.parser = "rules(no api key)" if state.get("use_llm", True) else "rules"

    return {"rules_order": rules_order, "llm_order": llm_order, "parser": rules_order.parser}


def compare(state: QuoteState) -> Dict[str, Any]:
    """节点 4：字段级合并。规则优先，缺字段用 LLM 补，冲突单独记录。"""
    primary = state["rules_order"]
    secondary = state.get("llm_order")
    if secondary is None:
        return {"order": primary, "conflicts": []}
    merged, conflicts = merge_orders(primary, secondary)
    return {"order": merged, "conflicts": conflicts, "parser": "merged"}


def after_compare(state: QuoteState) -> str:
    """条件边：有冲突就去二次校验，否则直接校验。"""
    return "llm_judge" if state.get("conflicts") else "validate"


def llm_judge(state: QuoteState) -> Dict[str, Any]:
    """节点 5：LLM 二次校验。失败则采用规则版，并记下原因。"""
    try:
        result = llm.judge(
            state["raw_text"],
            state["rules_order"],
            state["llm_order"],
            api_key=state["api_key"],
            model=state.get("model") or DEFAULT_MODEL,
            base_url=state.get("base_url") or DEFAULT_BASE_URL,
        )
        order = result["order"]
        order.parser = "llm-judge"
        return {
            "order": order,
            "judge_choice": result["choice"],
            "judge_confidence": result["confidence"],
        }
    except Exception as exc:  # noqa: BLE001 - 裁判失败不能阻断下单
        order = state["rules_order"]
        order.warnings.append("二次校验失败，采用规则版：%s" % exc)
        return {"order": order, "judge_error": str(exc)}


def validate(state: QuoteState) -> Dict[str, Any]:
    """节点 6：槽位/范围/一致性校验。缺槽位时不允许聚合金额。"""
    order = state["order"]
    return {"issues": validate_order(order), "missing": detect_missing(order)}


def after_validate(state: QuoteState) -> str:
    """条件边：有任何校验问题就去澄清（不聚合金额），否则直接计价。"""
    return "clarify" if state.get("issues") else "price"


def clarify(state: QuoteState) -> Dict[str, Any]:
    """节点 7：把缺失项写进订单警告，并标记 blocked（不出金额）。"""
    state["order"].warnings.extend(state.get("issues", []))
    return {"blocked": True}


def price(state: QuoteState) -> Dict[str, Any]:
    """节点 8：数出三个量，各自乘单价生成三行明细。"""
    book: PriceBook = state["price_book"]
    quantities = compute_quantities(state["order"], state.get("typeset_default", "none"))
    lines = book.build_lines(quantities)
    return {"quantities": quantities, "lines": lines}


def sum_node(state: QuoteState) -> Dict[str, Any]:
    """节点 9：三行小计相加得到总价。"""
    return {"total": sum_total(state["lines"])}


def annotate(state: QuoteState) -> Dict[str, Any]:
    """节点 10：生成假设和追问，不影响金额。"""
    book: PriceBook = state["price_book"]
    assumptions, questions = book.collect_notes(
        state["order"], state["quantities"], state.get("typeset_default", "none")
    )
    return {"assumptions": assumptions, "questions": questions}


def _write_log(state: QuoteState, quote) -> None:
    """写一条决策日志；log_path=False 时关闭，失败不影响主流程。"""
    log_path = state.get("log_path")
    if log_path is False:
        return
    rules_order = state.get("rules_order")
    llm_order = state.get("llm_order")
    log_decision(
        {
            "input": state.get("raw_text"),
            "parser": quote.order.parser,
            "llm_attempts": getattr(state.get("llm_order"), "llm_attempts", 0)
            if state.get("llm_order")
            else 0,
            "rules_groups": [g.as_dict() for g in rules_order.groups] if rules_order else [],
            "llm_groups": [g.as_dict() for g in llm_order.groups] if llm_order else [],
            "conflicts": state.get("conflicts", []),
            "judge": state.get("judge_choice"),
            "issues": state.get("issues", []),
            "confirmations": quote.confirmations,
            "blocked": quote.blocked,
            "total": str(quote.total),
        },
        path=log_path if isinstance(log_path, str) else None,
    )


def render(state: QuoteState) -> Dict[str, Any]:
    """节点 11：组装 Quote，再渲染成 Markdown 或 JSON。"""
    from .models import Quote

    book: PriceBook = state["price_book"]
    common = dict(
        pricing_version=book.version,
        currency=book.currency,
        order=state["order"],
        typeset_default=state.get("typeset_default", "none"),
    )

    if state.get("blocked"):
        quote = Quote(
            lines=[],
            total=Decimal("0"),
            assumptions=[],
            questions=state.get("issues", []),
            blocked=True,
            **common
        )
        _write_log(state, quote)
        return {"quote": quote, "output": to_markdown(quote)}

    quote = Quote(
        lines=state["lines"],
        total=state["total"],
        assumptions=state.get("assumptions", []),
        questions=state.get("questions", []),
        confirmations=detect_confirmations(state["order"]),
        **common
    )
    if state.get("output_mode") == "json":
        output = json.dumps(to_json(quote), ensure_ascii=False, indent=2)
    else:
        output = to_markdown(quote)
    _write_log(state, quote)
    return {"quote": quote, "output": output}


def build_graph() -> Any:
    """把节点和边拼起来，返回编译后的图。"""
    builder = StateGraph(QuoteState)

    for name, fn in [
        ("ingest", ingest),
        ("load_pricebook", load_pricebook),
        ("dual_parse", dual_parse),
        ("compare", compare),
        ("llm_judge", llm_judge),
        ("validate", validate),
        ("clarify", clarify),
        ("price", price),
        ("sum", sum_node),
        ("annotate", annotate),
        ("render", render),
    ]:
        builder.add_node(name, fn)

    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "load_pricebook")
    builder.add_edge("load_pricebook", "dual_parse")
    builder.add_edge("dual_parse", "compare")
    # 条件边 1：合并后有没有冲突
    builder.add_conditional_edges(
        "compare", after_compare, {"llm_judge": "llm_judge", "validate": "validate"}
    )
    builder.add_edge("llm_judge", "validate")
    # 条件边 2：校验后缺不缺字段
    builder.add_conditional_edges(
        "validate", after_validate, {"clarify": "clarify", "price": "price"}
    )
    builder.add_edge("clarify", "render")  # 缺槽位：不聚合金额，直接出异常卡
    builder.add_edge("price", "sum")
    builder.add_edge("sum", "annotate")
    builder.add_edge("annotate", "render")
    builder.add_edge("render", END)

    return builder.compile()


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """编译一次，进程内复用。"""
    return build_graph()


def invoke_graph(
    text: str,
    pricing_path: Optional[str] = None,
    typeset_default: str = "none",
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    use_llm: bool = True,
    output_mode: str = "markdown",
    log_path: Any = None,
) -> Dict[str, Any]:
    """跑一次图，返回最终 State（含 quote 和 output）。"""
    initial: QuoteState = {
        "raw_text": text,
        "pricing_path": pricing_path,
        "typeset_default": typeset_default,
        "use_llm": use_llm,
        "api_key": api_key or "",
        "model": model,
        "base_url": base_url,
        "output_mode": output_mode,
        "log_path": log_path,
    }
    return get_graph().invoke(initial)


def quote_with_graph(text: str, **kwargs: Any) -> Any:
    """跑一次图，只要 Quote 对象（和 agent.quote 返回值结构一致）。"""
    return invoke_graph(text, **kwargs)["quote"]
