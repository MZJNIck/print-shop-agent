# 代码走读：一句中文，怎么变成一张报价单

这份文档按**代码执行顺序**走：数据从哪进来、经过哪个函数、被改成了什么、最后怎么出去。
每一站都给出「输入变量的真实值 → 关键代码（带行号）→ 输出变量的真实值」。

配合命令一起看：

```bash
python -m printshop --trace "帮我打一份合同，一共 10 页，装订成 1 本"
```

文档里的真实值来自 2026-11-02 的实际运行（Python 3.11，uv 环境）。

**当前版本默认走 `graph.py`（LangGraph）；`--no-graph` 走 `agent.py` 的顺序调用。两条路径输出一致，测试锁着。**

---

## 0. 总调用栈

```
python -m printshop "帮我打一份合同，一共 10 页，装订成 1 本"
│
├─ __main__.py:5                入口，sys.exit(main())
│
├─ cli.py  main()               argv -> argparse.Namespace -> texts: list[str]
│   │
│   ├─ config.py  load_config()  读 config.yaml（api_key/model/价目表/口径）
│   │
│   ├─ 默认：graph.py（LangGraph 图，State 在节点间传递）
│   │   ├─ ingest            校验原话
│   │   ├─ load_pricebook    读 pricing.yaml（版本 + 三个单价）
│   │   ├─ dual_parse        双跑：rules.parse_order + llm.parse
│   │   ├─ compare           字段级合并（merge.merge_orders）
│   │   ├─ llm_judge         冲突时二次校验（llm.judge）
│   │   ├─ validate          槽位/范围/一致性（validator.validate_order）
│   │   ├─ clarify           缺字段 -> 收集问题
│   │   ├─ price             Order -> 三个量 + 三行明细
│   │   ├─ sum               小计相加 -> total
│   │   ├─ annotate          假设 + 追问
│   │   └─ render            Quote -> Markdown / JSON
│   │
│   └─ --no-graph：agent.quote()（顺序调用，与上图等价）
│       ├─ agent.py:60  parse() -> rules.parse_order() / llm.parse()
│       └─ agent.py:61  pricebook.quote()
│               = compute_quantities -> build_lines -> sum_total -> collect_notes
│
└─ cli.py:185  to_markdown(quote)  Quote -> 屏幕上的报价单文本
```

数据形态一共变 4 次：

| 阶段 | 类型 | 真实值 |
|---|---|---|
| 命令行 | `list[str]` | `['帮我打一份合同，一共 10 页，装订成 1 本']` |
| argparse | `Namespace` | `text=[...]`, `json=False`, `demo=False` … |
| 解析 | `Order` | `groups=[Group('合同',10,1,None)]`, `books=1` |
| 计价 | `Quote` | 3 行明细, `total=Decimal('25.00')` |
| 渲染 | `str` / `dict` | Markdown 表格 / 12 字段 JSON |

---

## 1. 站点 1：入口与参数（`__main__.py` → `cli.py:139`）

`python -m printshop` 先执行包里的 `__main__.py`：

```python
# printshop/__main__.py
from .cli import main
if __name__ == "__main__":
    sys.exit(main())
```

`main()` 第一件事是把命令行解析成 `Namespace`（cli.py:140）：

```python
args = build_parser().parse_args(argv)
```

`text` 参数定义为 `nargs="*"`（cli.py:38），所以收成**列表**。真实结果：

```
text            = ['帮我打一份合同，一共 10 页，装订成 1 本']
json            = False
demo            = False
batch           = None
verbose         = False
trace           = False
pricing         = None
typeset_default = 'none'
no_llm          = False
api_key         = None
model           = None
base_url        = None
```

接着按顺序判断走哪条路（cli.py:150-160）：

```python
if args.demo:            # 跑内置 5 条样例
elif args.batch:         # 跑文件，每行一条
elif args.text:          # 单条文本
else:                    # 交互模式
```

你的输入走第三支，把列表拼回字符串（cli.py:158）：

```python
texts = [" ".join(args.text)]
```

`--trace` 是另一条支路（cli.py:162-167）：调 `trace_run` 后直接 `return 0`，不会走普通输出。

---

## 2. 站点 2：读配置，构造 Agent（`config.py` + `agent.py:16-36`）

`cli.py` 的 main 先 `load_config(args.config)` 读 `config.yaml`，按优先级合并：

```
--api-key  >  DEEPSEEK_API_KEY  >  config.yaml  >  代码默认值
```

然后构造 `PrintShopAgent`，构造函数做四件事：

```python
self.pricebook = PriceBook.load(pricing_path)   # 读 pricing.yaml
self.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
self.model = model
self.base_url = base_url
self.typeset_default = typeset_default
self.use_llm = use_llm
```

`PriceBook.load`（pricing.py:`_load_file`）按扩展名读取：`.yaml/.yml` 用 `yaml.safe_load`，其它按 JSON。结果：

```
pricebook.version = '2026-10-30'
pricebook.items = {
  'typeset': {'label': '排版费', 'basis': '源页面', 'unit_price': '3.00', ...},
  'print':   {'label': '打印费', 'basis': '实际打印页', 'unit_price': '0.50', ...},
  'bind':    {'label': '装订费', 'basis': '册', 'unit_price': '20.00', ...}
}
```

注意单价存的是**字符串** `"3.00"`，为的是后面用 `Decimal` 精确计算，不碰浮点。

本机 `config.yaml` 的 `api_key` 为空、环境变量也没有 → 传入 `""`。再算（agent.py:35-36）：

```python
return bool(self.use_llm and self.api_key and self.api_key.strip())
# bool(True and "" and ...) = False
```

**`llm_ready = False`**，这个值决定下一站的分叉。

---

## 3. 站点 3：`agent.quote` / `agent.parse` 的分叉（`agent.py:38-61`）

`main` 里对每个 text 调 `agent.quote(text)`（cli.py:169）：

```python
def quote(self, text: str) -> Quote:
    order = self.parse(text)                       # 先解析
    return self.pricebook.quote(order, self.typeset_default)   # 再计价
```

`parse` 第一行就是分叉（agent.py:40）：

```python
if self.llm_ready:                  # False，跳过
    try:
        return llm.parse(...)       # 有 key 走这里
    except Exception:
        order = rules.parse_order(text)   # 失败降级
order = rules.parse_order(text)           # 无 key 走这里
order.parser = "rules(no api key)"
return order
```

本机走 `rules.parse_order`，真实输出：

```
order.parser = 'rules(no api key)'
order.groups = [Group(name='合同', source_pages=10, copies=1, typeset=None)]
order.books  = 1
order.bind   = True
```

下面拆 `rules.parse_order` 内部。函数从 rules.py:121 开始，到 219 结束，一共 7 段。

---

## 4. 站点 4：`rules.parse_order` 内部（rules.py:121-219）

### 4.0 函数骨架（rules.py:121-136）

```python
def parse_order(text: str) -> Order:
    t = normalize(text)              # 规范化
    spans = _find_spans(t)           # 找"封面/目录/正文/合同…"这些组词
    order = Order(raw=text, parser="rules")
    groups = {}
    def group(name):                 # 按名字取组，没有就新建
        if name not in groups: groups[name] = Group(name=name)
        return groups[name]
    for _, _, name in spans:         # 先按文本顺序建好组
        group(name)
    explicit_copies = set()          # 记录哪些组的份数是明确写的
```

这一步的中间值（样例 1）：

```
t     = '帮我打一份合同,一共 10 页,装订成 1 本'
spans = [(5, 7, '合同')]           # 组词"合同"在位置 5-7
groups 先建出 {'合同': Group(name='合同')}
```

### 4.1 规范化 `normalize`（rules.py:60-70）

把全角标点转半角、压缩空白。中文语义不变，只是让正则好写。

```
输入 : 帮我打一份合同，一共 10 页，装订成 1 本
输出 : 帮我打一份合同,一共 10 页,装订成 1 本
```

### 4.2 找组词 `_find_spans`（rules.py:72-91）

在文本里找所有"内容名词"（封面/目录/正文/合同/论文/PPT…），得到 `(start, end, name)` 列表。
如果只找到泛词（文件/资料/材料），也会收；如果一个都没有，第 6 段会兜底建组。

样例 5 的真实结果（位置即字符下标）：

```
spans = [(0,2,'封面'), (3,5,'目录'), (11,13,'正文'), (19,21,'正文'),
         (27,29,'封面'), (29,31,'目录'), (44,46,'封面'), (46,48,'目录')]
```

### 4.3 页数（rules.py:138-147）

```python
for m in re.finditer(rf"({NUM})\s*页", t):
    n = cn_to_int(m.group(1))                      # "10" -> 10
    targets = _collect_before(t, spans, m.start()) # 这个页数归谁？
    if targets:
        for name in targets: group(name).source_pages = n
    else:
        global_pages = n                           # 归不到具体组，先记全局
```

`_collect_before`（rules.py:97-118）的规则：从数字往前看，最近的组词如果和数字之间只隔着"各/和/打/共…"这类连接词，就归给它；继续往前，还能隔着连接词找到下一个组词就继续收，遇到数字或实词就停。

样例 1 的真实推演：

```
t = '帮我打一份合同,一共 10 页,装订成 1 本'
匹配到 "10 页" @ 11
最近的组词 end<=11 的是 合同(5,7)
gap = t[7:11] = ',一共 '   ← 含"一"，不是连接词
→ targets = []  → global_pages = 10
```

样例 5 的真实推演：

```
"1 页" @ 7 ：目录(3,5) gap="各 " 通过 → 目录；再往前 封面(0,2) gap="和" 通过 → 封面
             → 封面 1 页、目录 1 页
"30 页"@14：正文(11,13) gap=" " 通过 → 正文；再往前 gap=t[5:11]="各 1 页、" 含数字，停
             → 正文 30 页
```

### 4.4 份数（rules.py:149-159）

```python
for m in re.finditer(rf"({NUM})\s*份", t):
    n = cn_to_int(m.group(1))
    targets = _collect_before(t, spans, m.start())
    if targets:
        for name in targets:
            group(name).copies = n
            explicit_copies.add(name)     # 标记"这份数是明说的"
    else:
        global_copies = n                 # "每页打 3 份"这种，先记全局
```

样例 2 的推演：

```
t = 'PPT 共 20 页,每页打 3 份,装成 2 册'
"3 份" @ 15：PPT(0,3) 的 gap = ' 共 20 页,每页打 ' 含数字 → 不通过
→ targets = []  → global_copies = 3
（第 7 段会把它补给 PPT）
```

样例 5 的推演：

```
"2 份" @ 23：正文(19,21) gap="打 " → 正文 copies=2
"1 份" @ 34：目录(29,31) gap="各打 " → 目录；再往前 封面(27,29) gap="" → 封面
             → 封面、目录 copies=1
```

### 4.5 装订（rules.py:161-175）

分两个正则，**先处理"各装订一本"，再处理普通装订**：

```python
# 各装订一本：每份各装一册 -> 册数 = 份数 × 本数
for m in re.finditer(rf"各\s*装(?:订|成|订成)?\s*(?:成\s*)?({NUM})\s*(?:册|本)", t):
    per_copy = max([g.copies for g in groups.values()] + [global_copies or 1])
    books = max(books, n * max(per_copy, 1))

# 装订成 X 本 / 装成 X 册 / 装 X 本
for m in re.finditer(rf"(?:装订|装|订)\s*(?:订成|成)?\s*({NUM})\s*(?:册|本)", t):
    books = max(books, n)
```

样例 3 的推演：

```
t = '论文 80 页打两份,各装订一本'
第一个正则匹配 "各装订一本"：n=1
per_copy = max(组内份数=1, global_copies=2) = 2
books = max(0, 1*2) = 2
第二个正则又匹配 "装订一本"：books = max(2,1) = 2
→ books = 2（每份各装一本，共 2 本）
```

样例 1 的推演：

```
"装订成 1 本" @ 16：第二个正则匹配（"装订" + 可选"成" + "1 本"）
books = 1
```

### 4.6 排版（rules.py:177-193）

```python
for m in re.finditer("排版", t):
    window = t[max(0, m.start() - 6):m.start()]     # 只看前 6 个字
    negative = re.search(r"(不要|不用|无需|不需要|不必|别|不)", window)
    value = not bool(negative)
    targets = _collect_before(t, spans, m.start())
    if targets:
        for name in targets: group(name).typeset = value
    else:
        typeset_global = value

if typeset_global is None and re.search(r"只(?:要|需|是)?(?:打印|印)", t):
    typeset_global = False      # "只要打印" = 不排版
```

为什么只看 6 个字：`"不需要装订，需要排版"` 里，如果看太远会把前一句的"不"算到"排版"头上，误判成不排版。这个坑修过，有回归测试盯着。

样例 5 的推演：

```
"排版" @ 51：window = t[45:51] = "也算要" → 无否定 → True
_collect_before：目录(44,46)? 最近 end<=51 的是 目录(46,48)
  gap=t[48:51]="也算要" → 也/算/要 都是连接词 → 目录
  再往前 封面(44,46) gap="" → 封面
→ 封面、目录 typeset=True；正文没提，保持 None
```

### 4.7 装订否定（rules.py:195-200）

```python
if re.search(r"(不要|不用|无需|不需要|不|免)装订", t):
    bind = False
    books = 0
```

样例 4 `"只要打印，不要装订：手册 15 页"` 命中，`bind=False, books=0`。否定优先于前面匹配到的册数。

### 4.8 兜底建组（rules.py:202-205）

如果全文一个组词都没找到（比如"帮我打印 3 页"），就按文档类型建一个组：

```python
doc = re.search(r"(合同|论文|简历|手册|PPT|报告|标书|图纸|文件|资料|材料)", t)
group(doc.group(1) if doc else "文件")
```

### 4.9 全局属性补全（rules.py:207-219）

前面归不到具体组的页数/份数/排版，在这里补给"没有显式值"的组：

```python
for g in groups.values():
    if g.source_pages == 0 and global_pages is not None:
        g.source_pages = global_pages
    if g.name not in explicit_copies and global_copies is not None:
        g.copies = global_copies
    if g.typeset is None and typeset_global is not None:
        g.typeset = typeset_global

order.groups = list(groups.values())
order.books = books
```

样例 1 走完这 7 段，得到：

```
Order(
  groups=[Group(name='合同', source_pages=10, copies=1, typeset=None)],
  books=1,
  bind=True,
  parser='rules(no api key)'
)
```

---

## 5. 站点 5：计价 `pricing.quote`（pricing.py:46-131）

### 5.1 三个量（pricing.py:56-63）

```python
use_all = typeset_default == "all"

def is_typeset(group):
    return use_all if group.typeset is None else bool(group.typeset)

typeset_pages = sum(g.source_pages for g in order.groups if is_typeset(g))
print_pages   = order.total_print_pages
books         = 0 if order.bind is False else order.books
```

样例 1 的真实值：

```
typeset_pages = 0      （typeset 是 None，默认口径 none 视为不排版）
print_pages   = 10 × 1 = 10
books         = 1
```

样例 5 的真实值：

```
typeset_pages = 1 + 1 = 2          （封面、目录显式 True；正文 None 不计）
print_pages   = 1×1 + 1×1 + 30×2 = 62
books         = 1
```

### 5.2 三行明细（pricing.py:65-83）

```python
quantities = [("typeset", typeset_pages), ("print", print_pages), ("bind", books)]
for key, qty in quantities:
    unit_price = self.unit_price(key)                 # "3.00" -> Decimal('3.00')
    subtotal = money(Decimal(qty) * unit_price)       # 数量 × 单价，量化到分
```

`money()`（pricing.py:20-22）：

```python
return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
```

用 Decimal 而不是 float，是为了 15 × 0.5 稳定等于 7.50，不会变成 7.499999。

样例 1 的真实三行：

```
QuoteLine('typeset', '排版费', '源页面',      qty=0,  unit=3.00,  subtotal=0.00)
QuoteLine('print',   '打印费', '实际打印页',  qty=10, unit=0.50,  subtotal=5.00)
QuoteLine('bind',    '装订费', '册',          qty=1,  unit=20.00, subtotal=20.00)
```

### 5.3 加总（pricing.py:83）

```python
total = money(sum((line.subtotal for line in lines), Decimal("0")))
# 0.00 + 5.00 + 20.00 = 25.00
```

### 5.4 假设与追问（pricing.py:85-120）

- `assumptions`：默认排版口径、不要装订、份数与册数不一致（样例 2 会多一行）
- `questions`：缺页数、份数无效、没识别出内容、LLM 降级原因

这两组字段都不参与金额，只影响报价单的"说明"和"是否完整"。

### 5.5 返回 Quote（pricing.py:122-131）

带上 `pricing_version`、`lines`、`total`、`order`、`assumptions`、`questions`。
版本号必须一起返回，报价单上要印出来。

---

## 6. 站点 6：渲染（render.py:13-110）

`to_json`（render.py:13-52）把 Quote 摊平成 12 个字段：

```
pricing_version, currency, parser, input, typeset_default,
order, line_items, print_breakdown, total, assumptions, questions, complete
```

`to_markdown`（render.py:54-110）就是按顺序拼字符串：标题 → 表格 → 合计 → 打印明细 → 假设 → 待确认 → 解析器。

两者都只是**读** Quote，不改任何数据。

---

## 7. 完整例子：样例 5 从进入到输出

一句输入：

```
封面和目录各 1 页、正文 30 页，正文打 2 份，封面目录各打 1 份，装 1 本，封面目录也算要排版
```

| 阶段 | 数据 |
|---|---|
| 规范化 | `封面和目录各 1 页、正文 30 页,正文打 2 份,封面目录各打 1 份,装 1 本,封面目录也算要排版` |
| 组词 | 封面、目录、正文、封面、目录、封面、目录（共 8 个 span） |
| 页数 | 封面 1、目录 1、正文 30 |
| 份数 | 正文 2、封面 1、目录 1 |
| 装订 | books=1 |
| 排版 | 封面 True、目录 True、正文 None |
| Order | 三个 Group，books=1 |
| 计价 | 排版 2×3=6、打印 62×0.5=31、装订 1×20=20 |
| Quote | total=57.00，假设 2 条 |
| 输出 | Markdown 表格 + 明细 + 假设 |

---

## 8. 文件地图

| 文件 | 行数 | 职责 | 关键函数 |
|---|---|---|---|
| `printshop/__main__.py` | 6 | 入口 | — |
| `printshop/config.py` | 53 | config.yaml 读取与优先级 | `load_config` |
| `printshop/decision_log.py` | 24 | 决策日志（JSONL） | `log_decision` |
| `printshop/cli.py` | 217 | 参数、分发、交互、trace；默认调图 | `main` (150), `trace_run` (77) |
| `printshop/graph.py` | 271 | LangGraph：11 节点（双跑/合并/校验/澄清） | `build_graph` (207), `quote_with_graph` (278) |
| `printshop/agent.py` | 61 | 顺序编排（`--no-graph`） | `parse` (38), `quote` (59) |
| `printshop/rules.py` | 308 | 非模型解析（词法归一 + 槽位抽取） | `parse_order` (188) |
| `printshop/llm.py` | 269 | LLM 抽取 + 二次校验 | `parse` (176), `judge` (226) |
| `printshop/merge.py` | 73 | 双跑结果的字段级合并 | `merge_orders` (40) |
| `printshop/validator.py` | 43 | 槽位、范围、一致性校验 | `validate_order` (17) |
| `printshop/pricing.py` | 174 | 计价（4 个可组合函数） | `compute_quantities` (53), `quote` (163) |
| `printshop/models.py` | 81 | 数据模型 | `Group` (14), `Order` (38), `Quote` (66) |
| `printshop/render.py` | 95 | 渲染（Quote → 文本/JSON） | `to_markdown` (54), `to_json` (13) |

核心依赖关系（箭头表示"调用"）：

```
cli -> graph -> rules / llm / merge / validator / pricing / render
cli -> agent -> rules / llm / pricing
pricing -> models
render  -> models
```

`graph` 只做编排，所有计算仍复用 `pricing` / `rules` / `llm`；`pricing` 不依赖自然语言层，所以可以直接构造 Order 单测（tests/test_pricing.py）。

---

## 9. 读代码的三条建议

1. **先看 models.py**：81 行，所有数据长什么样，看完再往下就不迷路。
2. **再看 pricing.py**：131 行，纯算术，没有正则、没有网络，最容易读懂。
3. **最后看 rules.py**：219 行，全项目最绕的地方，按上面 7 段的顺序读，每段只干一件事。
