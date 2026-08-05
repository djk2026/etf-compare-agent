"""
ETF 对比分析 Agent — Python 数据服务
基于 FastAPI，3 个端点：basic / snapshot / performance
数据源：东方财富 + 新浪财经公开接口
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import urllib.request
import json
import re
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── FastAPI 应用 ──────────────────────────────────────────────

app = FastAPI(
    title="ETF Compare Data Service",
    description="为 Dify ETF 对比 Agent 提供 ETF 基础信息、实时快照、历史表现的查询服务",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 请求/响应模型 ───────────────────────────────────────────

class CodesRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=5, description="ETF 代码列表，如 ['510300','159915']")

class BasicInfo(BaseModel):
    code: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    tracking_index: Optional[str] = None
    industry: Optional[str] = None
    fund_type: Optional[str] = None
    fund_size: Optional[float] = None
    management_company: Optional[str] = None
    establishment_date: Optional[str] = None

class SnapshotInfo(BaseModel):
    code: str
    name: Optional[str] = None
    price: Optional[float] = None
    prev_close: Optional[float] = None
    change_percent: Optional[float] = None
    open_price: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None

class PerformanceInfo(BaseModel):
    code: str
    name: Optional[str] = None
    returns: Optional[dict] = None  # {week1, month1, month3, month6, year1}

# ── 工具函数 ──────────────────────────────────────────────────

HEADERS_EASTMONEY = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://fund.eastmoney.com/",
    "Accept": "*/*",
}

HEADERS_SINA = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}


def infer_exchange(code: str) -> str:
    """根据代码前缀推断交易所"""
    if code.startswith(("51", "56", "58")):
        return "sh"
    if code.startswith(("15", "16")):
        return "sz"
    return "sh"


def to_sina_symbol(code: str) -> Optional[str]:
    """ETF 代码 → 新浪查询符号"""
    if code.startswith(("51", "56", "58")):
        return f"sh{code}"
    if code.startswith(("15", "16")):
        return f"sz{code}"
    return None


# ── 东方财富基金列表过滤常量 ────────────────────────────────

# 非 A 股关键词（港股、美股、跨境等）
NON_A_KEYWORDS = [
    "恒生", "港股", "纳斯达克", "标普", "日经", "德国", "法国", "韩国",
    "印度", "越南", "MSCI", "中概互联", "H股", "国企指数", "美股", "海外",
    "全球", "亚太", "新兴市场", "欧洲", "美国",
]

# 非权益类名称关键词
NON_EQUITY_NAME = [
    "货币", "保证金", "短融", "债", "转债", "固收", "添益", "日利", "理财", "现金",
]

# 非权益类 type 字段
NON_EQUITY_TYPE = ["货币型", "债券型"]

# ETF 代码前缀规则
SH_ETF_PREFIXES = ("51", "56", "58")
SZ_ETF_PREFIXES = ("159", "16")


def is_a_share(name: str) -> bool:
    """判断是否为 A 股相关 ETF"""
    for kw in NON_A_KEYWORDS:
        if kw in name:
            return False
    return True


def is_equity(name: str, fund_type: str) -> bool:
    """判断是否为权益类基金（排除货币、债券）"""
    for kw in NON_EQUITY_TYPE:
        if kw in fund_type:
            return False
    for kw in NON_EQUITY_NAME:
        if kw in name:
            return False
    return True


def is_etf_like(code: str) -> bool:
    """判断是否为场内可交易 ETF"""
    if code.startswith(SH_ETF_PREFIXES):
        if len(code) >= 3 and code[2] == "9":  # 519xxx = 场外基金
            return False
        return True
    if code.startswith(SZ_ETF_PREFIXES):
        return True
    return False


# ── 名称解析工具 ──────────────────────────────────────────────

# 常见基金公司关键词 → 公司全称
COMPANY_KEYWORDS = [
    ("华泰柏瑞", "华泰柏瑞基金管理有限公司"),
    ("易方达", "易方达基金管理有限公司"),
    ("华夏", "华夏基金管理有限公司"),
    ("南方", "南方基金管理股份有限公司"),
    ("广发", "广发基金管理有限公司"),
    ("富国", "富国基金管理有限公司"),
    ("博时", "博时基金管理有限公司"),
    ("嘉实", "嘉实基金管理有限公司"),
    ("招商", "招商基金管理有限公司"),
    ("天弘", "天弘基金管理有限公司"),
    ("国泰", "国泰基金管理有限公司"),
    ("鹏华", "鹏华基金管理有限公司"),
    ("银华", "银华基金管理有限公司"),
    ("华安", "华安基金管理有限公司"),
    ("工银瑞信", "工银瑞信基金管理有限公司"),
    ("汇添富", "汇添富基金管理股份有限公司"),
    ("景顺长城", "景顺长城基金管理有限公司"),
    ("万家", "万家基金管理有限公司"),
    ("中欧", "中欧基金管理有限公司"),
    ("交银施罗德", "交银施罗德基金管理有限公司"),
    ("兴证全球", "兴证全球基金管理有限公司"),
    ("建信", "建信基金管理有限责任公司"),
    ("平安", "平安基金管理有限公司"),
    ("国联安", "国联安基金管理有限公司"),
    ("海富通", "海富通基金管理有限公司"),
]

# 常见指数关键词 → 指数名称
INDEX_KEYWORDS = [
    ("沪深300", "沪深300指数"),
    ("中证500", "中证500指数"),
    ("中证1000", "中证1000指数"),
    ("中证2000", "中证2000指数"),
    ("上证50", "上证50指数"),
    ("上证180", "上证180指数"),
    ("上证指数", "上证综合指数"),
    ("科创50", "科创50指数"),
    ("科创100", "科创100指数"),
    ("科创创业50", "科创创业50指数"),
    ("创业板", "创业板指数"),
    ("创业板50", "创业板50指数"),
    ("深证100", "深证100指数"),
    ("深证成指", "深证成份指数"),
    ("中证红利", "中证红利指数"),
    ("中证银行", "中证银行指数"),
    ("证券公司", "证券公司指数"),
    ("中证军工", "中证军工指数"),
    ("中证医疗", "中证医疗指数"),
    ("中证消费", "中证消费指数"),
    ("中证白酒", "中证白酒指数"),
    ("中证畜牧", "中证畜牧养殖指数"),
    ("半导体", "半导体指数"),
    ("芯片", "芯片指数"),
    ("新能源", "新能源指数"),
    ("光伏", "光伏产业指数"),
    ("新能源汽车", "新能源汽车指数"),
    ("电池", "电池指数"),
    ("碳中和", "碳中和指数"),
    ("人工智能", "人工智能指数"),
    ("计算机", "计算机指数"),
    ("通信", "通信指数"),
    ("5G", "5G通信指数"),
    ("大数据", "大数据指数"),
    ("云计算", "云计算指数"),
    ("传媒", "传媒指数"),
    ("游戏", "游戏指数"),
    ("食品饮料", "食品饮料指数"),
    ("医药", "医药指数"),
    ("创新药", "创新药指数"),
    ("中药", "中药指数"),
    ("房地产", "房地产指数"),
    ("基建", "基建工程指数"),
    ("电力", "电力指数"),
    ("煤炭", "煤炭指数"),
    ("钢铁", "钢铁指数"),
    ("有色金属", "有色金属指数"),
    ("化工", "化工指数"),
    ("农业", "农业指数"),
    ("汽车", "汽车指数"),
    ("稀土", "稀土指数"),
    ("黄金", "黄金指数"),
    ("国防", "国防指数"),
]


def extract_management_company(name: str) -> Optional[str]:
    """从基金名称中提取基金公司（东方财富格式：指数名+ETF+公司名）"""
    for kw, full_name in COMPANY_KEYWORDS:
        if kw in name:
            return full_name
    return None


def infer_tracking_index(name: str) -> Optional[str]:
    """从基金名称中推断跟踪指数"""
    for kw, index_name in INDEX_KEYWORDS:
        if kw in name:
            return index_name
    return None


def infer_industry(name: str, fund_type: str) -> Optional[str]:
    """推断行业分类"""
    industry_map = [
        (["沪深300", "上证50", "上证180", "深证100", "中证100"], "大盘蓝筹"),
        (["中证500", "中证800"], "中盘成长"),
        (["中证1000", "中证2000", "国证2000"], "小盘成长"),
        (["科创50", "科创100", "科创创业50", "创业板"], "科技创新"),
        (["半导体", "芯片", "5G", "人工智能", "计算机", "通信", "大数据", "云计算", "电子"], "科技/TMT"),
        (["新能源", "光伏", "新能源汽车", "电池", "碳中和", "电力"], "新能源"),
        (["医药", "创新药", "中药", "医疗", "生物医药"], "医药健康"),
        (["银行", "证券", "金融", "保险"], "金融"),
        (["消费", "食品饮料", "白酒", "家电"], "消费"),
        (["军工", "国防", "航"], "国防军工"),
        (["房地产", "基建"], "地产基建"),
        (["煤炭", "钢铁", "有色金属", "化工", "稀土", "黄金"], "资源周期"),
        (["传媒", "游戏"], "传媒娱乐"),
        (["红利"], "红利策略"),
    ]
    for keywords, industry in industry_map:
        for kw in keywords:
            if kw in name:
                return industry
    return "综合/其他"


# ── 基金列表缓存 ──────────────────────────────────────────────

_fund_list_cache: Optional[dict[str, dict]] = None
_fund_list_cache_time: float = 0
CACHE_TTL = 600  # 缓存 10 分钟


def fetch_fund_list() -> dict[str, dict]:
    """
    从东方财富下载并解析全量基金列表，返回 {code: info} 字典
    数据缓存 10 分钟，避免每次请求都下载
    """
    global _fund_list_cache, _fund_list_cache_time

    # 缓存命中
    if _fund_list_cache and (time.time() - _fund_list_cache_time) < CACHE_TTL:
        return _fund_list_cache

    logger.info("正在从东方财富下载全量基金列表...")
    url = "http://fund.eastmoney.com/js/fundcode_search.js"
    req = urllib.request.Request(url, headers=HEADERS_EASTMONEY)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"下载基金列表失败: {e}")
        raise HTTPException(status_code=502, detail="东方财富数据接口不可用")

    # 定位数组: var r = [ ... ];
    try:
        idx = raw.index("var r = [") + len("var r = [")
        content = raw[idx:-2]  # 去掉末尾 "];"
    except ValueError:
        logger.error("基金列表格式解析失败")
        raise HTTPException(status_code=502, detail="东方财富数据格式异常")

    entries = content.split("],[")
    result = {}
    seen = set()

    for i, entry in enumerate(entries):
        if i == 0:
            entry = entry[1:]  # 去掉开头的 [
        if i == len(entries) - 1:
            entry = entry[:-1]  # 去掉末尾的 ]

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

        result[code] = {
            "name": name,
            "exchange": infer_exchange(code),
            "fund_type_raw": fund_type,
            "is_a_share": is_a_share(name),
            "management_company": extract_management_company(name),
            "tracking_index": infer_tracking_index(name),
            "industry": infer_industry(name, fund_type),
        }

    _fund_list_cache = result
    _fund_list_cache_time = time.time()
    logger.info(f"基金列表已缓存，共 {len(result)} 只 A 股 ETF")
    return result


# ── 基金详情（规模、成立日期） ──────────────────────────────

def fetch_fund_detail(code: str) -> dict:
    """
    从东方财富基金详情数据获取规模、成立日期等补充信息
    数据源：http://fund.eastmoney.com/pingzhongdata/{code}.js
    """
    url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
    result = {}

    # ── 方式1：pingzhongdata JS 文件（规模） ──
    try:
        req = urllib.request.Request(url, headers=HEADERS_EASTMONEY)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"获取 {code} pingzhongdata 失败: {e}")
        raw = ""

    if raw:
        # 净资产规模：Data_assetAllocation → series[name="净资产"] → data 最后一项
        m_alloc = re.search(r"Data_assetAllocation\s*=\s*(\{[\s\S]*?\});", raw)
        if m_alloc:
            try:
                alloc = json.loads(m_alloc.group(1))
                for s in alloc.get("series", []):
                    if "净资产" in s.get("name", ""):
                        data = s.get("data", [])
                        if data:
                            result["fund_size"] = round(float(data[-1]), 2)
                        break
            except (json.JSONDecodeError, ValueError, IndexError):
                pass

    # ── 方式2：基金 HTML 页面（成立日期） ──
    try:
        html_url = f"http://fund.eastmoney.com/{code}.html"
        req = urllib.request.Request(html_url, headers=HEADERS_EASTMONEY)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # 搜索 "成立日期" 或 "成立时间"
        for keyword in ["成立日期", "成立时间"]:
            idx = html.find(keyword)
            if idx > 0:
                snippet = html[idx:idx + 200]
                # 提取日期格式: YYYY-MM-DD 或 YYYY年MM月DD日
                m_date = re.search(r"(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}[日]?)", snippet)
                if m_date:
                    date_str = m_date.group(1)
                    date_str = date_str.replace("年", "-").replace("月", "-").replace("日", "")
                    result["establishment_date"] = date_str
                    break
    except Exception as e:
        logger.warning(f"获取 {code} HTML 页面失败: {e}")

    return result


# ── 新浪财经实时快照 ──────────────────────────────────────────

def fetch_snapshots(codes: list[str]) -> dict[str, Optional[dict]]:
    """
    批量获取 ETF 实时快照
    数据源：新浪财经 https://hq.sinajs.cn
    """
    # 代码 → 新浪符号映射
    sina_symbols = []
    sym_to_code = {}
    for code in codes:
        sym = to_sina_symbol(code)
        if sym:
            sina_symbols.append(sym)
            sym_to_code[sym] = code

    if not sina_symbols:
        return {code: None for code in codes}

    url = "https://hq.sinajs.cn/list=" + ",".join(sina_symbols)
    req = urllib.request.Request(url, headers=HEADERS_SINA)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")  # 新浪返回 GBK 编码
    except Exception as e:
        logger.error(f"新浪快照请求失败: {e}")
        return {code: None for code in codes}

    results = {}

    for line in raw.strip().split("\n"):
        # 匹配每条数据: var hq_str_sh510300="..."
        for sina_sym, code in sym_to_code.items():
            if sina_sym not in line:
                continue
            try:
                start = line.index('"') + 1
                end = line.rindex('"')
                parts = line[start:end].split(",")
                if len(parts) < 10:
                    results[code] = None
                    continue

                # 字段解析（PROJECT_MANUAL 参考 2）
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
                if abs(change_pct) >= 0.30:  # A 股 ETF 单日不可能超 ±30%
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


# ── 新浪 K 线历史数据（计算 performance） ────────────────────

def resolve_kline_symbol(code: str) -> str:
    """ETF 代码 → 新浪 K 线符号"""
    if code.startswith(("51", "56", "58")):
        return f"sh{code}"
    if code.startswith(("15", "16")):
        return f"sz{code}"
    return f"sh{code}"


def calculate_returns(kline_data: list[dict]) -> dict[str, Optional[float]]:
    """
    根据 K 线数据计算各区间涨跌幅，返回小数形式
    days_back: 5交易日≈1周, 21≈1月, 63≈3月, 126≈6月, 250≈1年
    """
    if not kline_data or len(kline_data) < 2:
        return {}

    try:
        latest_close = float(kline_data[-1]["close"])
    except (KeyError, ValueError, IndexError):
        return {}

    if latest_close == 0:
        return {}

    def get_return(days_back: int) -> Optional[float]:
        if days_back >= len(kline_data):
            return None
        try:
            past_close = float(kline_data[-1 - days_back]["close"])
        except (KeyError, ValueError):
            return None
        if past_close == 0:
            return None
        return round((latest_close - past_close) / past_close, 6)

    return {
        "week1": get_return(5),
        "month1": get_return(21),
        "month3": get_return(63),
        "month6": get_return(126) if len(kline_data) > 126 else None,
        "year1": get_return(250) if len(kline_data) > 250 else None,
    }


def fetch_performance(code: str, days: int = 250) -> Optional[dict]:
    """获取单只 ETF 历史表现"""
    kline_symbol = resolve_kline_symbol(code)
    url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={kline_symbol}&scale=240&datalen={days}"
    )

    try:
        req = urllib.request.Request(url, headers=HEADERS_SINA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")  # 新浪 K 线也是 GBK
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) == 0:
            return None
        returns = calculate_returns(data)
        if not returns:
            return None
        name = data[-1].get("name", "") if data else ""
        return {"name": name, "returns": returns}
    except Exception as e:
        logger.warning(f"获取 {code} K 线数据失败: {e}")
        return None


def fetch_performances(codes: list[str]) -> dict[str, Optional[dict]]:
    """批量获取多只 ETF 历史表现（逐个请求，K 线接口不支持批量）"""
    results = {}
    for code in codes:
        results[code] = fetch_performance(code)
    return results


# ── 端点 ──────────────────────────────────────────────────────

@app.get("/")
def health_check():
    """健康检查"""
    return {"status": "ok", "service": "ETF Compare Data Service", "version": "1.0.0"}


@app.post("/api/etf/basic")
def get_etf_basic(req: CodesRequest):
    """
    获取 ETF 基础信息：名称、规模、费率、跟踪指数、成立日期等
    数据来源：东方财富 fund.eastmoney.com
    """
    fund_list = fetch_fund_list()
    results = {}

    for code in req.codes:
        fund = fund_list.get(code)

        if not fund:
            results[code] = {"code": code, "error": "invalid_code", "message": f"未找到代码 {code} 对应的 A 股 ETF"}
            continue

        entry = {
            "code": code,
            "name": fund["name"],
            "exchange": fund["exchange"],
            "tracking_index": fund.get("tracking_index"),
            "industry": fund.get("industry"),
            "fund_type": fund.get("fund_type_raw", "ETF"),
            "management_company": fund.get("management_company"),
            "fund_size": None,
            "establishment_date": None,
        }

        # 尝试获取补充信息（规模、成立日期）
        detail = fetch_fund_detail(code)
        if detail:
            entry["fund_size"] = detail.get("fund_size")
            entry["establishment_date"] = detail.get("establishment_date")

        results[code] = entry

    return results


@app.post("/api/etf/snapshot")
def get_etf_snapshot(req: CodesRequest):
    """
    获取 ETF 实时快照：最新净值、涨跌幅、折溢价率、成交额等
    数据来源：新浪财经 hq.sinajs.cn
    """
    snapshots = fetch_snapshots(req.codes)
    results = {}

    for code in req.codes:
        data = snapshots.get(code)
        if data is None:
            results[code] = {
                "code": code,
                "name": None,
                "price": None,
                "prev_close": None,
                "change_percent": None,
                "open_price": None,
                "high": None,
                "low": None,
                "volume": None,
                "amount": None,
                "error": "snapshot_unavailable",
                "message": f"ETF {code} 实时行情暂不可用（可能停牌或非交易时段）",
            }
        else:
            results[code] = {"code": code, **data}

    return results


@app.post("/api/etf/performance")
def get_etf_performance(req: CodesRequest):
    """
    获取 ETF 历史表现：近1周/1月/3月/6月/1年涨跌幅
    数据来源：新浪财经 K 线数据接口
    """
    performances = fetch_performances(req.codes)
    results = {}

    for code in req.codes:
        data = performances.get(code)
        if data is None:
            results[code] = {
                "code": code,
                "name": None,
                "returns": None,
                "error": "performance_unavailable",
                "message": f"ETF {code} 历史数据暂不可用",
            }
        else:
            results[code] = {
                "code": code,
                "name": data.get("name"),
                "returns": data.get("returns"),
            }

    return results


# ── 启动入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
