"""命令行入口。

用法：
    python -m printshop "帮我打一份合同，一共 10 页，装订成 1 本"
    python -m printshop --demo                 # 跑规格里的 5 条样例
    python -m printshop --demo --verbose       # 每条输出完整报价单
    python -m printshop --json "..."           # 机器可读报价单
    python -m printshop --batch examples/samples.txt
    python -m printshop                        # 交互模式
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .agent import PrintShopAgent
from .config import load_config
from .models import Quote
from .render import fmt, to_json, to_markdown

try:  # LangGraph 是可选依赖：没装也能用顺序路径
    from . import graph as graph_module
except Exception:  # noqa: BLE001
    graph_module = None

SAMPLES_FILE = Path(__file__).resolve().parent.parent / "examples" / "samples.txt"


def load_samples(path: Optional[str] = None) -> List[str]:
    p = Path(path) if path else SAMPLES_FILE
    texts: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            texts.append(line)
    return texts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printshop",
        description="打印店自然语言接单 Agent：自然语言 -> 可核对的报价单",
    )
    parser.add_argument("text", nargs="*", help="自然语言下单内容")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报价单")
    parser.add_argument("--demo", action="store_true", help="跑规格里的 5 条样例")
    parser.add_argument("--batch", metavar="FILE", help="批量跑文件，每行一条")
    parser.add_argument("--verbose", action="store_true", help="demo/batch 时输出完整报价单")
    parser.add_argument("--trace", action="store_true", help="单条输入，逐步打印内部流程")
    parser.add_argument("--pricing", metavar="FILE", help="价目表路径（默认读 config.yaml，缺省 pricing.yaml）")
    parser.add_argument("--config", metavar="FILE", help="运行配置（默认 config.yaml）")
    parser.add_argument(
        "--typeset-default",
        choices=["none", "all"],
        default=None,
        help="用户没提排版时按哪种口径计费（默认读 config.yaml，缺省 none）",
    )
    parser.add_argument("--no-llm", action="store_true", help="强制使用离线规则解析器")
    parser.add_argument(
        "--no-graph", action="store_true", help="不走 LangGraph，改用顺序调用（agent.quote）"
    )
    parser.add_argument("--no-log", action="store_true", help="不写 logs/decisions.jsonl")
    parser.add_argument(
        "--show-log", type=int, metavar="N", help="查看最近 N 条决策日志"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="deepseek api key；默认读环境变量 DEEPSEEK_API_KEY，留空则离线运行",
    )
    parser.add_argument("--model", default=None, help="默认 deepseek-flash")
    parser.add_argument("--base-url", default=None, help="默认 https://api.deepseek.com")
    return parser


def summary_line(index: int, text: str, quote: Quote) -> str:
    tail = "（待确认 %d 项）" % len(quote.questions) if quote.questions else ""
    return "[%d] 合计 %s 元 | 价目 %s | 解析器 %s%s\n    输入：%s" % (
        index,
        fmt(quote.total),
        quote.pricing_version,
        quote.order.parser,
        tail,
        text,
    )


def trace_run(agent: PrintShopAgent, text: str) -> None:
    """把一次下单从输入到报价单的内部步骤逐步打印出来。"""
    pb = agent.pricebook
    print("输入：%s" % text)
    print()

    print("[1] 读价目表 pricing.yaml")
    print(
        "    版本 %s：排版 %s 元/页，打印 %s 元/页，装订 %s 元/册"
        % (
            pb.version,
            fmt(pb.unit_price("typeset")),
            fmt(pb.unit_price("print")),
            fmt(pb.unit_price("bind")),
        )
    )
    print()

    print("[2] 听懂人话：这句话变成订单")
    order = agent.parse(text)
    print("    解析器：%s" % order.parser)
    for g in order.groups:
        typeset = {True: "要排版", False: "不排版", None: "没提"}[g.typeset]
        print("    - %s：源页 %d × %d 份，%s" % (g.name, g.source_pages, g.copies, typeset))
    print("    - 装订：%d 册" % order.total_books)
    print()

    quote = pb.quote(order, agent.typeset_default)
    print("[3] 按三条规则算钱 pricing.py")
    for line in quote.lines:
        print(
            "    %s：%d %s × %s 元 = %s 元"
            % (line.label, line.qty, line.basis, fmt(line.unit_price), fmt(line.subtotal))
        )
    print()

    print("[4] 加总")
    print("    " + " + ".join(fmt(line.subtotal) for line in quote.lines) + " = %s 元" % fmt(quote.total))
    print()

    print("[5] 出报价单 render.py")
    print()
    print(to_markdown(quote))


def repl(agent: PrintShopAgent, make_quote) -> int:
    print("打印店自然语言接单 Agent（价目版本 %s）" % agent.pricebook.version)
    print("直接输入下单内容；输入 exit / quit 退出。")
    while True:
        try:
            text = input("\n打印店> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in ("exit", "quit", "q"):
            return 0

        quote = make_quote(text)
        # 澄清闭环：缺槽位不聚合金额，等用户补充后合并回填再校验
        while quote.blocked:
            print()
            print(to_markdown(quote))
            try:
                supplement = input("\n补充（直接写缺少的信息，回车放弃）> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not supplement or supplement.lower() in ("exit", "quit", "q"):
                break
            text = text + "，" + supplement
            quote = make_quote(text)

        if quote.confirmations:
            print()
            print(to_markdown(quote))
            try:
                answer = input("\n确认按此计费？(y 继续 / n 重新输入) > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if answer not in ("y", "yes", "是", "确认"):
                continue
        else:
            print()
            print(to_markdown(quote))


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.show_log:
        from .decision_log import read_decisions

        records = read_decisions(args.show_log)
        if not records:
            print("暂无决策日志")
            return 0
        for index, record in enumerate(records, 1):
            print("%d. %s | %s" % (index, record.get("time", ""), record.get("input", "")))
            print(
                "   blocked=%s total=%s llm_attempts=%s conflicts=%s confirmations=%s"
                % (
                    record.get("blocked"),
                    record.get("total"),
                    record.get("llm_attempts"),
                    record.get("conflicts"),
                    record.get("confirmations"),
                )
            )
            if record.get("issues"):
                print("   issues=%s" % "；".join(record["issues"]))
        return 0

    config = load_config(args.config)

    # 优先级：命令行 > 环境变量 > config.yaml > 代码默认值
    api_key = args.api_key if args.api_key is not None else (
        os.environ.get("DEEPSEEK_API_KEY") or config.api_key
    )
    model = args.model or os.environ.get("DEEPSEEK_MODEL") or config.model
    base_url = args.base_url or os.environ.get("DEEPSEEK_BASE_URL") or config.base_url
    pricing_path = args.pricing or config.pricing_path
    typeset_default = args.typeset_default or config.typeset_default

    agent = PrintShopAgent(
        pricing_path=pricing_path,
        api_key=api_key,
        model=model,
        base_url=base_url,
        typeset_default=typeset_default,
        use_llm=not args.no_llm,
    )

    def make_quote(text: str) -> Quote:
        if graph_module is not None and not args.no_graph:
            return graph_module.quote_with_graph(
                text,
                pricing_path=pricing_path,
                typeset_default=typeset_default,
                api_key=agent.api_key,
                model=agent.model,
                base_url=agent.base_url,
                use_llm=agent.use_llm,
                log_path=False if args.no_log else None,
            )
        return agent.quote(text)

    if args.demo:
        texts = load_samples()
        if not texts:
            print("样例文件为空", file=sys.stderr)
            return 1
    elif args.batch:
        texts = load_samples(args.batch)
    elif args.text:
        texts = [" ".join(args.text)]
    else:
        return repl(agent, make_quote)

    if args.trace:
        if len(texts) != 1:
            print("--trace 只支持单条输入", file=sys.stderr)
            return 2
        trace_run(agent, texts[0])
        return 0

    if graph_module is None and not args.no_graph:
        print("提示：未安装 langgraph，已回退顺序调用（uv pip install langgraph）", file=sys.stderr)

    quotes = [make_quote(text) for text in texts]

    if args.json:
        payload = [to_json(quote) for quote in quotes]
        # 单条输出对象，多条输出数组，保证 stdout 始终是合法 JSON
        print(json.dumps(payload[0] if len(payload) == 1 else payload, ensure_ascii=False, indent=2))
        return 0

    for index, (text, quote) in enumerate(zip(texts, quotes), 1):
        if args.demo or args.batch:
            print(summary_line(index, text, quote))
            if args.verbose:
                print()
                print(to_markdown(quote))
            print()
        else:
            print(to_markdown(quote))
    return 0
