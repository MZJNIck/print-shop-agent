"""deepseek-flash 抽取层：只把自然语言变成订单 JSON，绝不参与计价。

API key 为空时由 agent.py 自动回退到 rules.py，因此离线也能跑通全部样例。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from .models import Group, Order


class LLMError(RuntimeError):
    pass


SYSTEM_PROMPT = """你是打印店接单助手。把用户的中文下单需求解析成一个 JSON 对象。
只输出 JSON，不要输出解释、不要 Markdown 代码块。

字段说明：
- groups: 数组，每个元素 {"name": 字符串, "source_pages": 整数, "copies": 整数, "typeset": true|false|null}
  * 每一组代表"一个源文档或文档的一部分"（如 封面/目录/正文/合同），各自有自己的源页数与打印份数
  * source_pages 是源页数，不是总打印页数；打多份时 copies 填份数，例如"80 页打两份"= source_pages 80, copies 2
  * "每页打 3 份"表示整组 copies=3
  * typeset：用户明确要求排版填 true；明确说"只要打印/不要排版"填 false；没提填 null
- books: 装订册数（整数；不装订填 0）
- bind: 是否装订（true/false/null）
- questions: 数组，信息不足时列出需要追问用户的问题（例如缺页数）

计价规则仅供理解语义，不要自己算钱：
排版费按"源页面"计费且同一源页只收一次；打印费 = 源页 × 份数；装订费按册计。"""

FEW_SHOT = [
    (
        "帮我打一份合同，一共 10 页，装订成 1 本",
        {"groups": [{"name": "合同", "source_pages": 10, "copies": 1, "typeset": None}],
         "books": 1, "bind": True, "questions": []},
    ),
    (
        "PPT 共 20 页，每页打 3 份，装成 2 册",
        {"groups": [{"name": "PPT", "source_pages": 20, "copies": 3, "typeset": None}],
         "books": 2, "bind": True, "questions": []},
    ),
    (
        "论文 80 页打两份，各装订一本",
        {"groups": [{"name": "论文", "source_pages": 80, "copies": 2, "typeset": None}],
         "books": 2, "bind": True, "questions": []},
    ),
    (
        "只要打印，不要装订：手册 15 页",
        {"groups": [{"name": "手册", "source_pages": 15, "copies": 1, "typeset": False}],
         "books": 0, "bind": False, "questions": []},
    ),
    (
        "封面和目录各 1 页、正文 30 页，正文打 2 份，封面目录各打 1 份，装 1 本，封面目录也算要排版",
        {"groups": [
            {"name": "封面", "source_pages": 1, "copies": 1, "typeset": True},
            {"name": "目录", "source_pages": 1, "copies": 1, "typeset": True},
            {"name": "正文", "source_pages": 30, "copies": 2, "typeset": None},
        ], "books": 1, "bind": True, "questions": []},
    ),
    (
        "帮我打印 3 页",
        {"groups": [{"name": "文件", "source_pages": 3, "copies": 1, "typeset": None}],
         "books": 0, "bind": False, "questions": []},
    ),
]


def _messages(text: str):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_text, answer in FEW_SHOT:
        msgs.append({"role": "user", "content": user_text})
        msgs.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    msgs.append({"role": "user", "content": text})
    return msgs


def _post(base_url: str, api_key: str, payload: dict, timeout: int) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:500]
        raise LLMError("HTTP %s: %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise LLMError("网络错误: %s" % exc.reason) from exc


def _extract_content(response: dict) -> str:
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("响应格式异常: %s" % json.dumps(response, ensure_ascii=False)[:300]) from exc


def _loads(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re_strip_fence(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError("模型没有返回合法 JSON: %s" % content[:300]) from exc


def re_strip_fence(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _to_order(obj: dict, text: str, parser_name: str) -> Order:
    groups = []
    for raw in obj.get("groups") or []:
        if not isinstance(raw, dict):
            continue
        try:
            pages = int(raw.get("source_pages") or 0)
            copies = int(raw.get("copies") or 1)
        except (TypeError, ValueError):
            pages, copies = 0, 1
        typeset = raw.get("typeset", None)
        if typeset is not None:
            typeset = bool(typeset)
        groups.append(
            Group(
                name=str(raw.get("name") or "文件"),
                source_pages=max(pages, 0),
                copies=max(copies, 1),
                typeset=typeset,
            )
        )

    if not groups:
        raise LLMError("模型没有解析出任何内容分组")

    try:
        books = int(obj.get("books") or 0)
    except (TypeError, ValueError):
        books = 0

    bind = obj.get("bind", None)
    if bind is not None:
        bind = bool(bind)

    questions = [str(q) for q in (obj.get("questions") or []) if str(q).strip()]

    order = Order(
        groups=groups,
        books=max(books, 0),
        bind=bind,
        raw=text,
        parser=parser_name,
    )
    order.warnings = questions
    return order


MAX_LLM_ATTEMPTS = 3


def validate_llm_output(obj: dict) -> List[str]:
    """LLM 输出的格式校验：返回问题列表，空列表表示通过。

    比 _to_order 更严格：结构不对就重试，而不是静默转成默认值。
    """
    problems: List[str] = []
    if not isinstance(obj, dict):
        return ["顶层不是 JSON 对象"]

    groups = obj.get("groups")
    if not isinstance(groups, list) or not groups:
        return ["缺少非空 groups 数组"]

    for index, group in enumerate(groups):
        prefix = "groups[%d]" % index
        if not isinstance(group, dict):
            problems.append("%s 不是对象" % prefix)
            continue
        name = group.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append("%s.name 缺失或不是字符串" % prefix)
        pages = group.get("source_pages")
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 0:
            problems.append("%s.source_pages 必须是非负整数" % prefix)
        copies = group.get("copies")
        if copies is not None and (
            not isinstance(copies, int) or isinstance(copies, bool) or copies < 1
        ):
            problems.append("%s.copies 必须是正整数" % prefix)
        typeset = group.get("typeset")
        if typeset not in (True, False, None):
            problems.append("%s.typeset 必须是 true/false/null" % prefix)
        books = group.get("books")
        if books is not None and (
            not isinstance(books, int) or isinstance(books, bool) or books < 0
        ):
            problems.append("%s.books 必须是非负整数或 null" % prefix)

    books = obj.get("books")
    if books is not None and (
        not isinstance(books, int) or isinstance(books, bool) or books < 0
    ):
        problems.append("books 必须是非负整数")
    bind = obj.get("bind")
    if bind not in (True, False, None):
        problems.append("bind 必须是 true/false/null")

    return problems


def parse(
    text: str,
    api_key: str,
    model: str = "deepseek-flash",
    base_url: str = "https://api.deepseek.com",
    timeout: int = 45,
    max_attempts: int = MAX_LLM_ATTEMPTS,
) -> Order:
    """调用模型解析；每次返回都过格式校验，不合法就带纠正提示重试。"""
    if not api_key or not api_key.strip():
        raise LLMError("没有配置 DEEPSEEK_API_KEY")

    base_messages = _messages(text)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        messages = list(base_messages)
        if attempt > 1:
            messages.append(
                {
                    "role": "user",
                    "content": "上一次输出不合法：%s。请只输出符合 schema 的 JSON，不要任何解释。"
                    % last_error,
                }
            )
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = _post(base_url, api_key, payload, timeout)
        except LLMError:
            # 某些兼容端不支持 response_format，去掉后重试一次
            payload.pop("response_format", None)
            response = _post(base_url, api_key, payload, timeout)

        try:
            obj = _loads(_extract_content(response))
            problems = validate_llm_output(obj)
            if problems:
                raise LLMError("格式不合法：" + "；".join(problems))
            order = _to_order(obj, text, model)
            order.llm_attempts = attempt
            return order
        except LLMError as exc:
            last_error = str(exc)
            continue

    raise LLMError("连续 %d 次输出不合法：%s" % (max_attempts, last_error))


JUDGE_SYSTEM = """你是打印店订单核对员。用户原话和两份解析结果给你，判断哪份正确。

- 规则版正确：choice = "rules"
- LLM 版正确：choice = "llm"
- 两份都错：给出修正版，choice = "fixed"，并填 order
- 无法判断：choice = "rules"，confidence 给低分

只输出 JSON，不要解释：
{"choice": "rules" | "llm" | "fixed",
 "order": {"groups": [{"name": "...", "source_pages": 0, "copies": 1, "typeset": null, "finish": null, "books": null}], "books": 0, "bind": true},
 "confidence": 0.0,
 "reason": "一句话"}
"""


def _order_to_dict(order: Order) -> dict:
    return {
        "groups": [g.as_dict() for g in order.groups],
        "books": order.books,
        "bind": order.bind,
    }


def judge(
    text: str,
    rules_order: Order,
    llm_order: Order,
    api_key: str,
    model: str = "deepseek-flash",
    base_url: str = "https://api.deepseek.com",
    timeout: int = 45,
    max_attempts: int = MAX_LLM_ATTEMPTS,
) -> dict:
    """二次校验：让模型在规则版/LLM 版之间做裁判，或给修正版。"""
    if not api_key or not api_key.strip():
        raise LLMError("没有配置 DEEPSEEK_API_KEY")

    user = "用户原话：%s\n\n规则版：%s\n\nLLM版：%s" % (
        text,
        json.dumps(_order_to_dict(rules_order), ensure_ascii=False),
        json.dumps(_order_to_dict(llm_order), ensure_ascii=False),
    )
    base_messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        messages = list(base_messages)
        if attempt > 1:
            messages.append(
                {
                    "role": "user",
                    "content": "上一次输出不合法：%s。请只输出符合 schema 的 JSON。"
                    % last_error,
                }
            )
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = _post(base_url, api_key, payload, timeout)
        except LLMError:
            payload.pop("response_format", None)
            response = _post(base_url, api_key, payload, timeout)

        try:
            obj = _loads(_extract_content(response))
            choice = obj.get("choice")
            if choice not in ("rules", "llm", "fixed"):
                raise LLMError("非法 choice: %r" % choice)
            if choice == "rules":
                order = rules_order
            elif choice == "llm":
                order = llm_order
            else:
                fixed = obj.get("order") or {}
                problems = validate_llm_output(fixed)
                if problems:
                    raise LLMError("fixed.order 格式不合法：" + "；".join(problems))
                order = _to_order(fixed, text, "llm-judge")

            try:
                confidence = float(obj.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0

            return {
                "choice": choice,
                "order": order,
                "confidence": max(0.0, min(confidence, 1.0)),
                "reason": str(obj.get("reason") or ""),
            }
        except LLMError as exc:
            last_error = str(exc)
            continue

    raise LLMError("judge 连续 %d 次输出不合法：%s" % (max_attempts, last_error))
