"""离线规则解析器（不依赖 API，无 key 也能跑）。

职责：把一句中文下单需求解析成 Order。它只负责"听懂"，
不做任何计价，金额一律交给 pricing.py 计算，保证可复算、可单测。

覆盖范围：
  * 规格里的 5 条样例（含"封面/目录/正文"分组与各自的份数）
  * 常见表达：X 页、打 X 份、每页打 X 份、装订成 X 本/X 册、各装订一本、
    要排版 / 不要排版 / 只要打印、不要装订
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import Group, Order

CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6,
    "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
NUM = r"[0-9一二三四五六七八九十百千两零〇壹贰叁肆伍陆柒捌玖拾佰仟]+"

# 具体内容分组词；"文件/资料"等泛词只在没有具体词时兜底
SPECIFIC_WORDS = ["封面", "目录", "正文", "合同", "论文", "简历", "手册", "标书", "报告", "图纸", "PPT"]
GENERIC_WORDS = ["文件", "资料", "材料"]

# 组词与数量之间的"连接词"：允许这些字符出现在组词和数字之间，
# 例如"封面和目录各 1 页"里，1 页同时属于封面和目录。
CONNECTORS = set(
    "各和与及、每均打打印装订成也才算要给我用把共总计合"
)

Span = Tuple[int, int, str]


def cn_to_int(text: str) -> int:
    """中文数字/阿拉伯数字 -> int，支持"二十""一百""两"等。"""
    text = text.strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    num = 0
    for ch in text:
        if ch in CN_DIGITS:
            num = CN_DIGITS[ch]
        elif ch in CN_UNITS:
            section += (num if num else 1) * CN_UNITS[ch]
            num = 0
        else:
            return 0
    return section + num


def normalize(text: str) -> str:
    """统一全角/半角与标点、压缩空白。

    量词不做文本替换：页/张/面 的别名直接写进页数正则，
    避免"张三""两面"这类同形词被误伤。
    """
    table = str.maketrans({
        "，": ",", "。": ".", "；": ";", "：": ":", "（": "(", "）": ")",
        "！": "!", "？": "?", "　": " ", "、": "、",
    })
    t = text.translate(table)
    t = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


QUOTED_TITLES = re.compile(r"《([^》]{1,40})》|「([^」]{1,40})」")

DOC_NAME = re.compile(
    r"(?:打印|复印|印|打)(?P<name>[^\d\s页份本册][\u4e00-\u9fa5A-Za-z0-9]{1,11}?)"
    r"(?=\s*\d+\s*页)"
)


def _extract_titles(t: str) -> Tuple[str, List[str]]:
    """把书名号/引号内容提成组名，并用等长占位符替换。

    等长替换保证后续 span 位置不变；占位符用全角"＃"，
    不会被数字、量词、组词正则匹配。
    """
    titles: List[str] = []

    def repl(match) -> str:
        content = (match.group(1) or match.group(2) or "").strip()
        if content:
            titles.append(content)
        return "＃" * len(match.group(0))

    return QUOTED_TITLES.sub(repl, t), titles


def _guess_doc_name(t: str) -> Optional[str]:
    """从"打印小张日记 10 页"这类句子猜文档名（仅在无已知组词时用）。"""
    match = DOC_NAME.search(t)
    if not match:
        return None
    name = match.group("name")
    if "的" in name:
        name = name.rsplit("的", 1)[-1]
    return name.strip() or None


def _find_spans(t: str) -> List[Span]:
    spans: List[Span] = []
    for word in SPECIFIC_WORDS:
        patterns = {word, word.lower()} if word.isascii() else {word}
        for pat in patterns:
            for m in re.finditer(re.escape(pat), t):
                spans.append((m.start(), m.end(), word))
    if not spans:
        for word in GENERIC_WORDS:
            for m in re.finditer(word, t):
                spans.append((m.start(), m.end(), word))
    spans = sorted(set(spans))
    # 去掉相互重叠的 span，保留更长的那个（避免"目录"命中"目录页"之类歧义时重复）
    result: List[Span] = []
    for span in spans:
        if result and span[0] < result[-1][1]:
            continue
        result.append(span)
    return result


def _only_connectors(gap: str) -> bool:
    return all(ch.isspace() or ch in CONNECTORS for ch in gap)


def _collect_before(t: str, spans: List[Span], pos: int) -> List[str]:
    """收集紧挨在 pos 之前、只隔着连接词的一组内容名。

    "封面和目录各 1 页" 中，数字 1 之前的最近组词是"目录"，
    再往前隔着"和"是"封面"，于是两者都算；遇到数字或其它实词就停。
    """
    picks: List[str] = []
    cur = pos
    while True:
        cand: Optional[Span] = None
        for span in spans:
            if span[1] <= cur and (cand is None or span[1] > cand[1]):
                cand = span
        if cand is None:
            break
        gap = t[cand[1]:cur]
        if not _only_connectors(gap):
            break
        if cand[2] not in picks:
            picks.insert(0, cand[2])
        cur = cand[0]
    return picks


def _is_ordinal(t: str, pos: int) -> bool:
    """数字前紧跟"第"就是序数：第 3 张 / 第 12 页，不能当数量。"""
    return t[max(0, pos - 3):pos].rstrip().endswith("第")


def _is_fuzzy(raw: str) -> bool:
    """纯中文数字、无单位、长度 >= 2，视为模糊量：两三页 / 一二份。"""
    if raw.isdigit():
        return False
    if any(unit in raw for unit in "十百千拾佰仟"):
        return False
    return len(raw) >= 2 and all(ch in CN_DIGITS for ch in raw)


def _nearest_group_before(
    t: str, spans: List[Span], pos: int, max_gap: int = 40
) -> Optional[str]:
    """找 pos 之前最近的组词（允许中间隔着页数），用于"每文档装几本"的归属。"""
    candidates = [span for span in spans if span[1] <= pos]
    if not candidates:
        return None
    span = max(candidates, key=lambda item: item[1])
    if pos - span[1] > max_gap:
        return None
    return span[2]


def parse_order(text: str) -> Order:
    t = normalize(text)
    t, titles = _extract_titles(t)
    spans = _find_spans(t)
    order = Order(raw=text, parser="rules")
    groups: Dict[str, Group] = {}

    def group(name: str) -> Group:
        if name not in groups:
            groups[name] = Group(name=name)
        return groups[name]

    # 先按出现顺序建组，保证报价单里分组顺序与用户描述一致
    for _, _, name in spans:
        group(name)

    explicit_copies: set = set()

    # 1) 页数：数字 + 量词（页/张/面）；跳过序数与模糊量
    global_pages: Optional[int] = None
    ambiguous_page: Optional[str] = None
    for m in re.finditer(rf"({NUM})\s*(?:页|张|面)", t):
        if _is_ordinal(t, m.start()):
            continue  # "第 3 张"是序数，不是 3 页
        if m.group(0).endswith("面") and m.group(1) == "两":
            continue  # "两面"=双面工艺，不是 2 页（第 3 步建模）
        raw = m.group(1)
        if _is_fuzzy(raw):
            ambiguous_page = raw
            continue  # "两三页"不猜，交给澄清
        n = cn_to_int(raw)
        targets = _collect_before(t, spans, m.start())
        if targets:
            for name in targets:
                group(name).source_pages = n
        else:
            global_pages = n

    if ambiguous_page:
        order.warnings.append(
            "页数「%s页」表述不明确，请给出具体页数" % ambiguous_page
        )

    # 2) 份数：X 份（"每页打 X 份"会落到全局份数，作用于所有组）
    global_copies: Optional[int] = None
    for m in re.finditer(rf"({NUM})\s*份", t):
        n = cn_to_int(m.group(1))
        targets = _collect_before(t, spans, m.start())
        if targets:
            for name in targets:
                group(name).copies = n
                explicit_copies.add(name)
        else:
            global_copies = n

    # 3) 装订册数
    #    "各装订一本" -> 每份各装一册，册数 = 份数 × 本数（全局）
    #    "装订成 X 本" -> 归属到最近的那份文档；没有文档时才是全局
    books = 0
    bind: Optional[bool] = None
    per_copy_books: List[Tuple[int, int]] = []
    for m in re.finditer(rf"各\s*装(?:订|成|订成)?\s*(?:成\s*)?({NUM})\s*(?:册|本)", t):
        n = cn_to_int(m.group(1))
        per_copy = max([g.copies for g in groups.values()] + [global_copies or 1])
        books = max(books, n * max(per_copy, 1))
        per_copy_books.append((m.start(), m.end()))
        bind = True

    for m in re.finditer(rf"(?:装订|装|订)\s*(?:订成|成)?\s*({NUM})\s*(?:册|本)", t):
        if any(start <= m.start() < end for start, end in per_copy_books):
            continue  # 已被"各装订一本"处理，不能重复计数
        n = cn_to_int(m.group(1))
        target = _nearest_group_before(t, spans, m.start())
        if target:
            group(target).books = n
        else:
            books = max(books, n)
        bind = True

    # 4) 排版：分组判断"要排版 / 不要排版"
    typeset_global: Optional[bool] = None
    for m in re.finditer("排版", t):
        # 只看紧邻的 6 个字符："不需要排版"算否定，但
        # "不需要装订，需要排版"里的"不"属于上一个分句，不能误判
        window = t[max(0, m.start() - 6):m.start()]
        negative = re.search(r"(不要|不用|无需|不需要|不必|别|不)", window)
        value = not bool(negative)
        targets = _collect_before(t, spans, m.start())
        if targets:
            for name in targets:
                group(name).typeset = value
        else:
            typeset_global = value

    if typeset_global is None and re.search(r"只(?:要|需|是)?(?:打印|复印|印)", t):
        typeset_global = False  # "只要打印" = 不排版

    # 5) 工艺：双面/单面（价目未定价，只记录，不影响金额）
    finish_global: Optional[str] = None
    for m in re.finditer(r"(双面|单面|两面)", t):
        finish = "双面" if m.group(1) in ("双面", "两面") else "单面"
        targets = _collect_before(t, spans, m.start())
        if targets:
            for name in targets:
                group(name).finish = finish
        else:
            finish_global = finish

    # 6) 装订否定优先
    if re.search(r"(不要|不用|无需|不需要|不|免)装订", t):
        bind = False
        books = 0
        for g in groups.values():
            g.books = None
    elif books > 0:
        bind = True

    # 7) 没有任何具体内容词时，按"书名号 -> 文档名 -> 泛词"兜底建组
    if not groups:
        for title in titles:
            group(title)
        if not groups:
            doc = re.search(r"(合同|论文|简历|手册|PPT|报告|标书|图纸|文件|资料|材料)", t)
            group(doc.group(1) if doc else (_guess_doc_name(t) or "文件"))

    # 8) 把全局属性补给没有显式写明的组
    for g in groups.values():
        if g.source_pages == 0 and global_pages is not None:
            g.source_pages = global_pages
        if g.name not in explicit_copies and global_copies is not None:
            g.copies = global_copies
        if g.typeset is None and typeset_global is not None:
            g.typeset = typeset_global
        if g.finish is None and finish_global is not None:
            g.finish = finish_global

    order.groups = list(groups.values())
    order.books = books
    order.bind = bind

    # 范围语义："除了封面，其余都打两份"——其余部分无法确定，必须澄清
    scope = re.search(r"(?:除了|除|不含|不包括|去掉)\s*([^,.;]{1,12})", t)
    if scope:
        order.warnings.append(
            "检测到范围语义「%s」：其余内容的页数/份数未明确，请补充"
            % scope.group(0).strip()
        )

    return order
