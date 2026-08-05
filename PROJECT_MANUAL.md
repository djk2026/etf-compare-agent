# ETF 对比分析 Agent — 完整项目手册

---

## 一、项目背景与动机

| 维度 | 内容 |
|------|------|
| **为什么要做** | 现有 ETF 持仓解释工具是"看懂持仓"，缺少"选哪只 ETF"的能力。面试需要一个独立的 Agent 项目展示 Dify 编排能力 |
| **项目定位** | 独立项目，不嵌入 ETF 工具，独立 Git 仓库，独立部署 |
| **求职目标** | AI 产品经理，简历第二个项目，展示 Agent 编排 + 数据工程 |
| **产品形态** | 用户输入 2-5 个 ETF 代码（逗号分隔）→ Agent 并行查询多维度数据 → 输出结构化对比报告 |
| **为什么用 Agent** | 对比需要并行查询多只 ETF 的基础信息、实时行情、历史表现，单次 LLM 调用做不到，Dify Agent 的并行 Tool 节点是天然解法 |

---

## 二、技术架构

```
用户浏览器
    ↓
Vercel 静态托管 (极简前端，一个 HTML 文件，Vue 3 CDN + marked.js)
    ↓
Vercel Serverless Function (代理 Dify API Key，解决前端暴露密钥问题)
    ↓
Dify Cloud Workflow Agent
    ↓ (并行 3 个 HTTP Request Tool)
Render 免费版托管的 Python FastAPI 数据服务 (3 端点)
    ↓
新浪财经 hq.sinajs.cn + 东方财富 fund.eastmoney.com
```

**关键约束**：
- 零云服务器，零 Docker，零自建数据库
- 依赖 Render（免费 Python 托管）+ Vercel（免费前端托管）+ Dify Cloud（免费版 200次/月）
- 本 Agent 项目**不依赖 ETF 持仓解释工具的任何代码或数据库**，完全独立

---

## 三、五阶段详细计划

### Stage 1: Python 数据服务 (4-6h)

#### 目录结构

```
etf-compare-agent/
├── data-service/
│   ├── main.py              # FastAPI 入口，3 端点
│   ├── requirements.txt     # fastapi, uvicorn, httpx
│   └── README.md            # API 文档
```

#### 三个 API 端点

**端点 1：`POST /api/etf/basic`**

入参：
```json
{"codes": ["510300", "159915"]}
```

出参（每个 ETF）：
- `name`: 基金名称
- `exchange`: "sh" 或 "sz"
- `tracking_index`: 跟踪指数名（如 "沪深300指数"）
- `industry`: 行业分类（如 "大盘蓝筹"）
- `fund_type`: "ETF" / "ETF联接" / "LOF"
- `fund_size`: 基金规模(亿元) — 从东方财富基金详情页获取
- `management_company`: 基金公司
- `establishment_date`: 成立日期

数据来源：东方财富 `http://fund.eastmoney.com/js/fundcode_search.js` 解析全量基金列表（格式见下方"技术参考"第1条），然后按 ETF 代码过滤。

**端点 2：`POST /api/etf/snapshot`**

入参：
```json
{"codes": ["510300", "159915"]}
```

出参（每个 ETF）：
- `name`: 名称
- `price`: 最新价
- `change_percent`: 涨跌幅（小数形式，如 -0.0123 = -1.23%）
- `prev_close`: 昨收
- `open_price`, `high`, `low`, `volume`, `amount`

数据来源：新浪财经 `https://hq.sinajs.cn/list=sh510300,sz159915`

**端点 3：`POST /api/etf/performance`**

入参：
```json
{"codes": ["510300", "159915"]}
```

出参（每个 ETF）：
- `name`: 名称
- `returns`: `{ "week1", "month1", "month3", "month6", "year1" }` — 各时间区间涨跌幅（小数形式）

数据来源：新浪财经 K 线 API `http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh510300&scale=240&datalen=250`

---

#### 技术参考（来自 ETF 工具的经验数据）

##### 参考 1：东方财富全量基金列表解析

URL: `http://fund.eastmoney.com/js/fundcode_search.js`

返回格式：
```javascript
var r = [["CODE","ABBR","NAME","TYPE","PINYIN"], ...]
```

每个元素格式：`["510300","华泰柏瑞沪深300ETF","华泰柏瑞沪深300ETF","指数型-股票","HTBHS300ETF"]`

ETF 代码前缀规则：
- 上海：51xxxx, 56xxxx, 58xxxx
- 深圳：159xxx, 16xxxx

**需要过滤的基金类型**：

非 A 股关键词（需过滤）：
```
恒生, 港股, 纳斯达克, 标普, 日经, 德国, 法国, 韩国, 印度, 越南,
MSCI, 中概互联, H股, 国企指数, 美股, 海外, 全球, 亚太, 新兴市场, 欧洲, 美国
```

非权益类关键词（需过滤）：
```
货币, 保证金, 短融, 债, 转债, 固收, 添益, 日利, 理财, 现金
```

非权益类 type 字段（需过滤）：`货币型`, `债券型`

**完整解析代码模板**（纯 urllib，无第三方依赖）：

```python
import urllib.request
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://fund.eastmoney.com/",
    "Accept": "*/*",
}

NON_A_KEYWORDS = [
    "恒生", "港股", "纳斯达克", "标普", "日经", "德国", "法国", "韩国",
    "印度", "越南", "MSCI", "中概互联", "H股", "国企指数", "美股", "海外",
    "全球", "亚太", "新兴市场", "欧洲", "美国",
]

NON_EQUITY_NAME = ["货币", "保证金", "短融", "债", "转债", "固收", "添益", "日利", "理财", "现金"]
NON_EQUITY_TYPE = ["货币型", "债券型"]

SH_ETF_PREFIXES = ("51", "56", "58")
SZ_ETF_PREFIXES = ("159", "16")


def is_a_share(name: str) -> bool:
    text = name.lower()
    for kw in NON_A_KEYWORDS:
        if kw in text:
            return False
    return True


def is_equity(name: str, fund_type: str) -> bool:
    for kw in NON_EQUITY_TYPE:
        if kw in fund_type:
            return False
    for kw in NON_EQUITY_NAME:
        if kw in name:
            return False
    return True


def is_etf_like(code: str) -> bool:
    """场内可交易品种"""
    if code.startswith(SH_ETF_PREFIXES):
        if len(code) >= 3 and code[2] == "9":  # 519xxx = 场外基金
            return False
        return True
    if code.startswith(SZ_ETF_PREFIXES):
        return True
    return False


def infer_exchange(code: str) -> str:
    if code.startswith(SH_ETF_PREFIXES):
        return "sh"
    if code.startswith(SZ_ETF_PREFIXES):
        return "sz"
    return "sh"


def fetch_fund_list() -> list[dict]:
    """从东方财富下载并解析全量基金列表"""
    url = "http://fund.eastmoney.com/js/fundcode_search.js"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    # 定位数组: var r = [ ... ];
    idx = raw.index("var r = [") + len("var r = [")
    content = raw[idx:-2]  # 去掉末尾 "];"

    entries = content.split("],[")
    result = []
    seen = set()

    for i, entry in enumerate(entries):
        if i == 0:
            entry = entry[1:]  # 去掉 [
        if i == len(entries) - 1:
            entry = entry[:-1]  # 去掉 ]

        parts = entry.split('","')
        if len(parts) < 4:
            continue

        code = parts[0].strip('"')
        name = parts[2].strip('"') if len(parts) > 2 else ""
        fund_type = parts[3].strip('"') if len(parts) > 3 else ""

        if not code or not name:
            continue
        if not is_etf_like(code):
            continue
        if code in seen:
            continue
        if not is_equity(name, fund_type):
            continue
        seen.add(code)

        result.append({
            "code": code,
            "name": name,
            "exchange": infer_exchange(code),
            "fund_type_raw": fund_type,
            "is_a_share": is_a_share(name),
        })

    return result
```

##### 参考 2：新浪财经实时快照解析

URL: `https://hq.sinajs.cn/list=sh510300,sz159915`

ETF 返回格式：
```
var hq_str_sh588000="科创50ETF华夏,2.133,2.125,2.028,2.141,2.011,...";
var hq_str_sz159915="创业板ETF易方达,1.850,1.840,1.835,1.855,1.820,...";
```

字段顺序（指数从第 0 个开始）：
- 0: name
- 1: open（今开）
- 2: prev_close（昨收）
- 3: price（当前价）
- 4: high
- 5: low
- 8: volume（成交量，手）
- 9: amount（成交额）

涨跌幅计算公式：`change_percent = (price - prev_close) / prev_close`

**ETF 代码 → 新浪代码映射规则**：
- 51xxxx, 56xxxx, 58xxxx → `sh` 前缀（如 sh510300）
- 159xxx, 16xxxx → `sz` 前缀（如 sz159915）

**完整快照解析代码模板**：

```python
import urllib.request

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}


def resolve_sina_symbol(code: str) -> str | None:
    """ETF 代码 → 新浪查询符号"""
    if code.startswith(("51", "56", "58")):
        return f"sh{code}"
    if code.startswith(("15", "16")):
        return f"sz{code}"
    return None


def fetch_snapshots(codes: list[str]) -> dict[str, dict | None]:
    """批量获取 ETF 快照"""
    sina_symbols = []
    code_map = {}
    for code in codes:
        s = resolve_sina_symbol(code)
        if s:
            sina_symbols.append(s)
            code_map[s] = code

    if not sina_symbols:
        return {}

    url = "https://hq.sinajs.cn/list=" + ",".join(sina_symbols)
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("gbk")  # 注意：GBK 编码！

    results = {}
    for line in raw.strip().split("\n"):
        for sina_sym, code in code_map.items():
            if sina_sym not in line:
                continue
            try:
                start = line.index('"') + 1
                end = line.rindex('"')
                parts = line[start:end].split(",")
                if len(parts) < 10:
                    results[code] = None
                    continue

                name = parts[0]
                open_price = float(parts[1]) if parts[1] else None
                prev_close = float(parts[2]) if parts[2] else None
                price = float(parts[3]) if parts[3] else None
                high = float(parts[4]) if parts[4] else None
                low = float(parts[5]) if parts[5] else None
                volume = float(parts[8]) if len(parts) > 8 and parts[8] else None
                amount = float(parts[9]) if len(parts) > 9 and parts[9] else None

                # 数据校验
                if price is None or prev_close is None or prev_close == 0:
                    results[code] = None
                    continue
                if price <= 0.01:  # 停牌/退市
                    results[code] = None
                    continue

                change_pct = (price - prev_close) / prev_close
                if abs(change_pct) >= 0.30:  # A股ETF不可能超±30%
                    results[code] = None
                    continue

                results[code] = {
                    "name": name,
                    "price": round(price, 4),
                    "prev_close": round(prev_close, 4),
                    "change_percent": round(change_pct, 6),
                    "open_price": round(open_price, 4) if open_price else None,
                    "high": round(high, 4) if high else None,
                    "low": round(low, 4) if low else None,
                    "volume": volume,
                    "amount": amount,
                }
            except (ValueError, IndexError):
                results[code] = None

    # 未匹配到的代码
    for code in codes:
        if code not in results:
            results[code] = None

    return results
```

##### 参考 3：新浪 K 线历史数据（计算 performance）

URL 格式：`http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh510300&scale=240&datalen=250`

返回格式（GBK 编码的 JSON）：
```json
[
  {"day":"2024-01-02","open":"3.500","high":"3.520","low":"3.480","close":"3.510","volume":"12345678"},
  {"day":"2024-01-03","open":"3.510","high":"3.550","low":"3.500","close":"3.530","volume":"23456789"},
  ...
]
```

**完整 performance 解析代码模板**：

```python
import urllib.request
import json


def resolve_kline_symbol(code: str) -> str:
    """ETF 代码 → 新浪 K 线符号"""
    if code.startswith(("51", "56", "58")):
        return f"sh{code}"
    if code.startswith(("15", "16")):
        return f"sz{code}"
    return f"sh{code}"


def calculate_returns(kline_data: list[dict]) -> dict:
    """根据 K 线数据计算各区间涨跌幅，返回小数形式"""
    if not kline_data or len(kline_data) < 2:
        return {}

    latest_close = float(kline_data[-1]["close"])
    if latest_close == 0:
        return {}

    def get_return(days_back: int) -> float | None:
        if days_back >= len(kline_data):
            return None
        past_close = float(kline_data[-1 - days_back]["close"])
        if past_close == 0:
            return None
        return round((latest_close - past_close) / past_close, 6)

    # 约 5 个交易日 = 1 周，约 21 个 = 1 月，约 63 个 = 3 月
    return {
        "week1": get_return(5),
        "month1": get_return(21),
        "month3": get_return(63),
        "month6": get_return(126) if len(kline_data) > 126 else None,
        "year1": get_return(250) if len(kline_data) > 250 else None,
    }


def fetch_performance(code: str, days: int = 250) -> dict | None:
    """获取单只 ETF 历史表现"""
    kline_symbol = resolve_kline_symbol(code)
    url = (
        f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={kline_symbol}&scale=240&datalen={days}"
    )
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read().decode("gbk")
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) == 0:
            return None
        returns = calculate_returns(data)
        if not returns:
            return None
        return {"name": "", "returns": returns}
    except Exception:
        return None


def fetch_performances(codes: list[str]) -> dict[str, dict | None]:
    """批量获取多只 ETF 历史表现"""
    results = {}
    for code in codes:
        results[code] = fetch_performance(code)
    return results
```

---

#### 数据降级策略

| 场景 | 行为 |
|------|------|
| 所有 3 端点正常 | 返回完整数据 |
| 某个端点超时 15s | 返回 `{"error": "timeout", "fallback": true}` |
| 东方财富接口不可用 | basic 端点返回兜底数据（名称从代码推断） |
| 非交易时间查快照 | 新浪返回的是上一交易日收盘数据，正常使用 |
| 无效 ETF 代码 | 返回 `{"error": "invalid_code", "code": "xxxxxx"}` |

#### 不依赖清单

- 不用 akshare（太重，import 慢）
- 不用 pandas（不需要数据分析）
- 不用 SQLite（不缓存，实时查询）
- 不用 MemoryCache（调用频率极低，不需要缓存）
- 只用 `fastapi` + `uvicorn` + `httpx` + `urllib`

#### Render 部署

- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- 免费版休眠：15 分钟无请求后休眠，首次唤醒 ~30 秒冷启动
- 给一个 `https://xxx.onrender.com` 域名

---

### Stage 2: Dify Workflow 搭建 (4-6h)

#### Dify 注册
- 去 `https://cloud.dify.ai` 注册
- 创建 **Workflow** 类型应用（不是 Chatflow，因为对比是一问一答，不需要多轮对话）

#### Workflow 节点拓扑

```
┌──────────────────┐
│  开始节点          │
│  inputs:          │
│    codes: string  │  ← 用户输入 "510300,159915,588000"
│    (逗号分隔)      │
└────────┬─────────┘
         ↓
┌──────────────────┐
│  Code 节点 #1:     │
│  "输入清洗"        │
│  输入: codes       │
│  逻辑:              │
│    1. split(",")   │
│    2. trim 空格     │
│    3. 去重          │
│    4. 校验格式(6位数)│
│    5. 限5只,超了截断│
│  输出:             │
│    cleaned_codes   │
│    (array)          │
└────────┬─────────┘
         ↓
    ┌────┴─────────────┐
    ↓                  ↓
┌────────────┐  ┌────────────────┐
│ Tool #1    │  │ Tool #2        │
│ getBasic   │  │ getSnapshot    │
│            │  │                │
│ URL:       │  │ URL:           │
│ POST Render│  │ POST Render    │
│ /api/etf/  │  │ /api/etf/      │
│ basic      │  │ snapshot       │
│            │  │                │
│ Body:      │  │ Body:          │
│ {codes:    │  │ {codes:        │
│  cleaned   │  │  cleaned       │
│ }          │  │ }              │
└──────┬─────┘  └───────┬────────┘
       ↓                ↓
┌────────────┐
│ Tool #3    │
│ getPerf    │
│            │
│ URL:       │
│ POST Render│
│ /api/etf/  │
│ performance│
│            │
│ Body:      │
│ {codes:    │
│  cleaned   │
│ }          │
└──────┬─────┘
       ↓
   ┌───┴────┬────┴─────┐
   ↓        ↓          ↓
┌────────────────────────────────┐
│  Code 节点 #2:                  │
│  "数据聚合与对比矩阵构建"         │
│  输入:                          │
│    basic_result (#1)            │
│    snapshot_result (#2)         │
│    performance_result (#3)      │
│  逻辑:                          │
│    1. 合并 3 个结果              │
│    2. 标记缺失维度               │
│       (fallback=true)           │
│    3. 构建对比表格              │
│    4. 识别差异最大的维度         │
│  输出: comparison_matrix         │
│        (结构化对比矩阵)           │
└────────────┬───────────────────┘
             ↓
┌────────────────────────────────┐
│  LLM 节点                       │
│  Model: deepseek-v4-flash       │
│  System: (见下方完整 Prompt)     │
│  User: {{#2.comparison_matrix}} │
│  Temperature: 0.3              │
│  Max tokens: 3000              │
│  额外参数:                      │
│  {"thinking":{"type":"disabled"}}│
│  输出: 结构化对比报告             │
└────────────┬───────────────────┘
             ↓
┌──────────────────┐
│  结束节点          │
│  outputs:          │
│    report: string  │
└──────────────────┘
```

**注意**：3 个 Tool 节点设为**并行执行**（Dify 画布上独立连线或设置并行）。

#### LLM System Prompt（完整版）

```
你是一个专业的 ETF 对比分析助手。你的任务是基于真实数据，帮用户对比多只 ETF 的核心维度差异。

## 行为准则

1. 禁止提供投资建议。不说"建议买入"、"推荐持有"、"这只更好"等结论性判断
2. 禁止编造数据。只基于提供的真实数据，缺失数据标注"暂无数据"
3. 必须用白话解释专业术语。如出现"跟踪误差"、"折溢价"、"夏普比率"等，要加简短解释
4. 底部必须标注："数据来源：新浪财经 / 东方财富公开数据，延迟约 15-30 分钟，仅供参考"
5. 结构化输出，格式见下方
6. 最多对比 5 只 ETF。如果输入超过 5 只，在报告中提示并仅展示前 5 只

## 输出格式

### 对比总览

用 Markdown 表格列出以下维度的对比：

| 维度 | ETF1(代码-名称) | ETF2(代码-名称) | ... |
|------|----------------|-----------------|-----|
| 跟踪指数 | xxx | xxx | |
| 基金规模 | xxx亿元 | xxx亿元 | |
| 管理费率 | 0.xx% | 0.xx% | |
| 成立时间 | xxxx年 | xxxx年 | |
| 今日涨跌 | +x.xx% | -x.xx% | |
| 近1月收益 | +x.xx% | +x.xx% | |
| 近3月收益 | +x.xx% | +x.xx% | |
| 行业分类 | xxx | xxx | |

### 逐只解读

每只 ETF 一段话（不超过 5 行），用白话说明：
- 它跟踪什么指数
- 规模意味着什么（规模大 = 流动性好）
- 费率高低对长期持有的影响
- 近期表现简述

### 维度对比总结

选择差异最大的 2-3 个维度做深入对比，解释差异的含义。

### 注意事项

提醒用户：
- 历史业绩不代表未来表现
- 费率、规模、跟踪误差是选 ETF 的核心维度
- 不同 ETF 可能跟踪同一指数，主要看费率和规模

---
数据来源：新浪财经 / 东方财富公开数据，延迟约 15-30 分钟，仅供参考。不构成投资建议。
```

#### 错误处理策略（在 Agent 中配置）

| 场景 | Agent 行为 |
|------|-----------|
| 全部 3 个 Tool 成功 | 正常生成完整报告 |
| 1 个 Tool 失败/超时 | 跳过该维度，报告中标注"该维度数据暂不可用" |
| 2 个 Tool 失败 | 用仅剩的数据生成精简版对比 |
| 全部 Tool 失败 | 输出"当前数据服务暂不可用，请稍后重试" |
| 用户输入无效代码 | Code 节点#1 校验后返回空数组 → LLM 输出"未找到有效 ETF 代码，请检查后重试" |

#### 调试技巧
- Dify 后台有"日志"功能，每个节点都能看输入输出
- 先用 Postman 验证你的 3 个 Render API 端点正常，再配 Dify Tool
- Code 节点里的 Python 沙箱环境有限，不要用复杂库

#### 发布到 Dify
- 搭建好 Workflow 后，点"发布"
- 得到一个 API 端点和一个公开 URL（形式：`https://udify.app/chat/xxxxx`）
- 公开 URL 自带的聊天界面也可以直接演示

---

### Stage 3: 极简前端 (3-4h)

#### 技术栈
- Vue 3 CDN（`https://unpkg.com/vue@3/dist/vue.global.js`）
- marked.js CDN（Markdown 渲染：`https://cdn.jsdelivr.net/npm/marked/marked.min.js`）
- 原生 CSS
- 单文件 `index.html`
- **不使用** npm install、Vite、Pinia、Vue Router、uni-app

#### 页面结构

```
┌──────────────────────────────┐
│  ETF 对比分析助手              │
│                              │
│  ┌────────────────────────┐  │
│  │ 输入ETF代码，逗号分隔...  │  │
│  └────────────────────────┘  │
│  [ 开始对比 ]                 │
│                              │
│  示例: 510300,159915,588000   │
│  ────────────────────────── │
│                              │
│  (Markdown 渲染结果)          │
│                              │
│  数据延迟约15-30分钟           │
└──────────────────────────────┘
```

#### 前端调用链路
前端不能直接调 Dify API（会暴露 API Key）。正确方式：

```
前端 fetch('POST /api/compare')
  → Vercel Serverless Function (compare.js)
  → Dify Workflow API (https://udify.app/api/workflows/run)
```

#### Vercel Serverless Function（`api/compare.js`）

```javascript
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { codes } = req.body;
  if (!codes || typeof codes !== 'string' || !codes.trim()) {
    return res.status(400).json({ error: '请提供 ETF 代码' });
  }

  try {
    const response = await fetch('https://udify.app/api/workflows/run', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.DIFY_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        inputs: { codes: codes.trim() },
        response_mode: 'blocking',
        user: 'anonymous',
      }),
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      return res.status(502).json({ error: `Dify API error: ${response.status}` });
    }

    const data = await response.json();
    // Dify Workflow 返回格式: { data: { outputs: { report: "..." } } }
    const report = data?.data?.outputs?.report || data?.data?.outputs?.text || '暂无分析结果';
    return res.json({ report });
  } catch (err) {
    return res.status(500).json({ error: '比对服务暂时不可用，请稍后重试' });
  }
}
```

#### Vercel 配置（`vercel.json`）

```json
{
  "functions": {
    "api/compare.js": {
      "runtime": "@vercel/node"
    }
  }
}
```

#### Vercel 环境变量
在 Vercel 项目 Settings → Environment Variables 中添加：
- Key: `DIFY_API_KEY`
- Value: `app-xxxxxxxxxxxxxx`（Dify 后台 → 应用 → API 访问 → API 密钥）

#### 部署方式
1. `npm i -g vercel`（一次性）
2. 在项目根目录执行 `vercel`，按提示关联项目
3. 或在 Vercel 网页直接拖文件夹

---

### Stage 4: API Key 安全 (1h)

此阶段融合到 Stage 3 中。核对清单：
- Dify API Key 仅存在于 Vercel 环境变量中
- 前端 `fetch('/api/compare', ...)`，不直接调 Dify
- 浏览器 Network 面板中看不到 Dify API Key
- `.gitignore` 中不提交任何 .env 文件

---

### Stage 5: 文档 + Git 交付 (2h)

#### Git 仓库最终结构

```
etf-compare-agent/
├── data-service/
│   ├── main.py              # FastAPI 入口，3 端点
│   ├── requirements.txt     # fastapi, uvicorn, httpx
│   └── README.md            # API 接口文档
├── dify/
│   ├── workflow-dsl.yml     # Dify Workflow 导出文件
│   └── README.md            # Dify 配置说明（Tool 配置 + Prompt + 截图）
├── frontend/
│   └── index.html           # 极简前端单页
├── api/
│   └── compare.js           # Vercel Serverless Function
├── vercel.json              # Vercel 部署配置
├── README.md                # 项目总览
├── docs/
│   └── PRD.md               # 产品需求文档
└── .gitignore
```

#### README.md 必须包含的章节

1. **项目简介**：一句话说清楚做什么
2. **为什么做**：从 ETF 工具发现对比需求缺口 → 用 Agent 解决
3. **为什么用 Agent**：并行 Tool 编排 vs 单次 LLM 调用的对比说明
4. **架构图**：Mermaid 格式
5. **快速体验**：
   - Dify 公开链接（可直接用）
   - Vercel 部署的网页链接
6. **技术选型**：Dify Cloud / Render / Vercel / FastAPI / DeepSeek
7. **本地开发**：如何启动数据服务
8. **API 文档**：3 个端点说明
9. **部署指南**：Render / Vercel / Dify 部署步骤

#### PRD.md 要点

- **产品边界**：仅 A 股 ETF，不提供投资建议
- **目标用户**：有 ETF 投资经验的基民，需要对比 2-3 只 ETF 时使用
- **核心指标**：从输入到出结果 < 15 秒（含 Render 冷启动 ~30 秒）
- **功能范围**：输入代码 → 对比报告，无搜索、无用户系统、无数据存储
- **不做什么**：不预测走势、不推荐买卖、不支持港股美股

#### `.gitignore`

```
__pycache__/
*.pyc
.env
.env.local
node_modules/
.vercel
```

---

## 四、ETF 工具踩过的坑（避免重犯）

| 踩过的坑 | 教训 | 对本项目的影响 |
|----------|------|---------------|
| **DeepSeek 流式返回兼容性问题** | 已否决 SSE 流式，全部用阻塞模式 | Dify Workflow 用 `response_mode: "blocking"` |
| **`response_format: {type: "json_object"}` 无效** | DeepSeek 不遵守，靠 Prompt 约束输出格式 | 不依赖 Dify 的结构化输出参数，靠 Prompt 约束 |
| **`max_tokens` 固定值导致 JSON 截断** | 多只 ETF 需要更大 token，已改为动态计算 | Dify LLM 节点 max_tokens 设 3000（足以覆盖 5 只对比） |
| **板块行情实时抓取超时** | `dataEnricher` 每次都超时拖慢响应，已移除 | 不额外抓取板块行情，只对比基础维度 |
| **AI 不可用无降级** | 已加规则解读兜底 | Agent 全部 Tool 失败 → 兜底提示文案 |
| **`thinking: {type:"disabled"}` 丢失** | DeepSeek V4 content 为空的核心修复 | 在 Dify LLM 节点的**额外参数**中必须加 `{"thinking": {"type": "disabled"}}`（JSON 格式手动输入） |
| **前端直接调 Python 服务** | 跨域问题，已改为 Express 中转 | 前端 → Vercel Serverless → Dify → FastAPI，没有直接跨域 |
| **新浪财经返回 GBK 编码** | UTF-8 decode 会乱码 | FastAPI 中必须 `.decode("gbk")` |
| **新浪请求缺少 Referer 被拒** | 返回 403 | Header 加 `Referer: https://finance.sina.com.cn` |
| **价格 <=0.01 的异常数据** | 停牌/退市基金的残留数据 | 快照解析加价格校验 |
| **涨跌幅 >±30% 的异常值** | A股 ETF 单日不可能 | 快照解析加涨跌幅校验 |
| **东方财富接口不稳定** | 偶尔不可用 | basic 端点加 try/except，失败返回 fallback |
| **新浪快照批量请求 URL 过长** | 单次最多支持约 800 个 | 只查 2-5 个 ETF，不会超 |
| **`一键启动.bat` 本地脚本** | 竞态条件不可靠 | 不用，用 Render + Vercel 部署 |

---

## 五、已否决的方案（不要回头）

| 方案 | 否决原因 |
|------|---------|
| 把 Dify 嵌入 ETF 工具的 AI 解读 | 增加延迟，违背"10秒看懂"的产品承诺 |
| 用 Dify 本地部署 Dify CE | 需要 6+ Docker 容器，无云服务器不可行 |
| 纯 Dify 配置（不写数据服务） | 像玩具项目，技能提升为零，面试说服力弱 |
| 把 Agent 项目放 ETF 工具仓库里 | Git 历史混乱，无法作为独立项目展示 |
| 前端用 uni-app | 本 Agent 项目不需要移动端适配，不需要重量框架 |
| 数据服务用 akshare | akshare 依赖太多，Render 冷启动慢 |
| 前端直接调 Dify API | 暴露 API Key |
| SSE 流式返回 | DeepSeek 流式兼容性问题，用 blocking 模式 |
| 对比超过 5 只 ETF | 报告会过长，LLM 输出质量下降 |

---

## 六、立即开始

**从 Stage 1 开始，先完整写出 `data-service/main.py`。**

不要分步写、不要边写边问——一次性输出完整可运行的 `main.py`，包含：
1. FastAPI 应用初始化
2. 3 个端点（basic / snapshot / performance）
3. 数据抓取函数（东方财富基金列表 / 新浪快照 / 新浪 K 线）
4. 数据清洗和校验
5. 错误处理和降级

代码模板参考本文档"技术参考"章节中的 Python 代码块，它们已经包含了完整的数据解析逻辑。

写完 main.py 后：
1. 写 `requirements.txt`
2. 本地用 `uvicorn main:app --reload` 测试
3. 用 Postman 验证 3 个端点
4. 部署到 Render

---

*手册生成时间：2026-08-05*
