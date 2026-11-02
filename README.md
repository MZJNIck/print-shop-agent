# 打印店自然语言接单 Agent

一句中文下单，输出可核对的报价单：**基数 / 单价 / 小计 / 总价**。金额由代码计算，不靠模型。

## 怎么启动

```bash
cd print-shop-agent
.venv\Scripts\python -m printshop "帮我打一份合同，一共 10 页，装订成 1 本"
```

换机器时先建环境：

```bash
uv venv
uv pip install -e ".[graph,dev]"
```

## 在哪输入自然语言

| 方式 | 命令 | 说明 |
|---|---|---|
| 单条 | `.venv\Scripts\python -m printshop "你的话"` | 直接回车 |
| 交互 | `.venv\Scripts\python -m printshop` | 出现 `打印店>` 提示符，一行一句，`exit` 退出 |
| 批量 | `.venv\Scripts\python -m printshop --batch examples/samples.txt` | 文件每行一句 |
| 样例 | `.venv\Scripts\python -m printshop --demo` | 跑 5 条规格样例 |

交互模式下，缺页数等槽位会追问，补充后自动合并再报价。

```bash
# 看决策日志（最近 5 条）
.venv\Scripts\python -m printshop --show-log 5
```

## 配置文件在哪改

| 改什么 | 改哪个文件 | 怎么改 |
|---|---|---|
| API key / 模型 / 价目路径 / 排版口径 | `config.yaml` | 直接编辑，保存后重跑 |
| 价格 | `pricing.yaml` | 改 `unit_price`，同时改 `version`（报价单会印版本） |

> 仓库里不含 `config.yaml`（它可能含真实 key，已被 `.gitignore` 排除），但带了模板 `config.template.yaml`。clone 后先复制一份：

```bash
copy config.template.yaml config.yaml
```

再按需改 `api_key` 即可。不复制也能跑（默认配置、离线规则）。

优先级：**命令行 > 环境变量 > config.yaml**。例如 `--api-key sk-...` 覆盖文件里的 key。

`config.yaml` 里的 `api_key` 留空也能跑（离线规则）；填了就走 deepseek-flash 双跑。

模型返回有**格式校验**（JSON 可解析、groups 非空、字段类型正确），不合法会带纠正提示自动重试，最多 3 次；仍失败则降级规则版，原因写进报价单。`--show-log` 里的 `llm_attempts` 能看到实际调用次数。

## 跑测试

```bash
.venv\Scripts\python -m pytest -q
```

当前 **108 条**，全离线、零网络，约 7 秒。

## 输出长什么样

完整时：

```
| 项目 | 计费基数 | 数量 | 单价 | 小计 |
| 打印费 | 实际打印页 | 10 | 0.50 | 5.00 |
| 装订费 | 册 | 1 | 20.00 | 20.00 |

合计：25.00 元
```

槽位不全时**不出金额**，只给异常卡和重输格式：

```
【无法报价】缺少必要信息，暂不聚合金额：
- 「合同」打印多少页？

请按以下格式重新输入：
  文档名 + 页数 + 打印份数 + [装订册数] + [是否排版]
```

如果份数与装订册数不一致（例如 3 份装 2 册），报价单会多一段「请确认」，金额照算：

```
### 请确认
- 份数 3 与装订册数 2 不匹配，是否继续按此计费？（如不认可，请按原格式重新输入）
```

交互模式下会直接问 `y 继续 / n 重新输入`；选 `n` 就丢弃这单、回到输入。

## 计费规则（一行）

排版 3 元/源页（同一源页只算一次）+ 打印 0.5 元/打印页 + 装订 20 元/册。

## 目录

```
printshop/            源码
tests/                测试（108 条）
config.template.yaml  运行配置模板（入库，key 为空）
config.yaml           本地配置（含你的 key，不入库）
pricing.yaml          价目表
logs/                 决策日志（--no-log 可关）
```

详细代码走读见 [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md)。
