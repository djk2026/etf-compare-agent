"""
ETF 对比分析 Agent — 共享数据抓取逻辑
供 Vercel Serverless Functions 导入使用
数据源：东方财富 + 新浪财经公开接口
"""

import urllib.request
import json
import re
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── HTTP Headers ─────────────────────────────────────────────

HEADERS_EASTMONEY = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://fund.eastmoney.com/",
    "Accept": "*/*",
}

HEADERS_SINA = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}

# ── 工具函数 ──────────────────────────────────────────────────

def infer_exchange(code: str) -> str:
    if code.startswith(("51", "56", "58")):
        return "sh"
    if code.startswith(("15", "16")):
        return "sz"
    return "sh"


def to_sina_symbol(code: str) -> Optional[str]:
    if code.startswith(("51", "56", "58")):
        return f"sh{code}"
    if code.startswith(("15", "16")):
        return f"sz{code}"
    return None


# ── 东方财富基金列表过滤常量 ────────────────────────────────

NON_A_KEYWORDS = [
    "恒生", "港股", "纳斯达克", "标普", "日经", "德国", "法国", "韩国",
    "印度", "越南", "MSCI", "中概互联", "H股", "国企指数", "美股", "海外",
    "全球", "亚太", "新兴市场", "欧洲", "美国",
]

NON_EQUITY_NAME = [
    "货币", "保证金", "短融", "债", "转债", "固收", "添益", "日利", "理财", "现金",
]

NON_EQUITY_TYPE = ["货币型", "债券型"]

SH_ETF_PREFIXES = ("51", "56", "58")
SZ_ETF_PREFIXES = ("159", "16")


def is_a_share(name: str) -> bool:
    for kw in NON_A_KEYWORDS:
        if kw in name:
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
    if code.startswith(SH_ETF_PREFIXES):
        if len(code) >= 3 and code[2] == "9":
            return False
        return True
    if code.startswith(SZ_ETF_PREFIXES):
        return True
    return False


# ── 名称解析 ──────────────────────────────────────────────────

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

INDEX_KEYWORDS = [
    ("沪深300", "沪深300指数"), ("中证500", "中证500指数"),
    ("中证1000", "中证1000指数"), ("中证2000", "中证2000指数"),
    ("上证50", "上证50指数"), ("上证180", "上证180指数"),
    ("上证指数", "上证综合指数"), ("科创50", "科创50指数"),
    ("科创100", "科创100指数"), ("科创创业50", "科创创业50指数"),
    ("创业板", "创业板指数"), ("创业板50", "创业板50指数"),
    ("深证100", "深证100指数"), ("深证成指", "深证成份指数"),
    ("中证红利", "中证红利指数"), ("中证银行", "中证银行指数"),
    ("证券公司", "证券公司指数"), ("中证军工", "中证军工指数"),
    ("中证医疗", "中证医疗指数"), ("中证消费", "中证消费指数"),
    ("中证白酒", "中证白酒指数"), ("中证畜牧", "中证畜牧养殖指数"),
    ("半导体", "半导体指数"), ("芯片", "芯片指数"),
    ("新能源", "新能源指数"), ("光伏", "光伏产业指数"),
    ("新能源汽车", "新能源汽车指数"), ("电池", "电池指数"),
    ("碳中和", "碳中和指数"), ("人工智能", "人工智能指数"),
    ("计算机", "计算机指数"), ("通信", "通信指数"),
    ("5G", "5G通信指数"), ("大数据", "大数据指数"),
    ("云计算", "云计算指数"), ("传媒", "传媒指数"),
    ("游戏", "游戏指数"), ("食品饮料", "食品饮料指数"),
    ("医药", "医药指数"), ("创新药", "创新药指数"),
    ("中药", "中药指数"), ("房地产", "房地产指数"),
    ("基建", "基建工程指数"), ("电力", "电力指数"),
    ("煤炭", "煤炭指数"), ("钢铁", "钢铁指数"),
    ("有色金属", "有色金属指数"), ("化工", "化工指数"),
    ("农业", "农业指数"), ("汽车", "汽车指数"),
    ("稀土", "稀土指数"), ("黄金", "黄金指数"),
    ("国防", "国防指数"),
]

# 跟踪指数名称 → 新浪指数代码（仅收录已验证可用的主流指数；未收录的跟踪误差返回暂无数据）
INDEX_CODE_MAP = {
    "沪深300指数": "sh000300",
    "中证500指数": "sh000905",
    "中证1000指数": "sh000852",
    "上证50指数": "sh000016",
    "上证180指数": "sh000010",
    "上证综合指数": "sh000001",
    "科创50指数": "sh000688",
    "创业板指数": "sz399006",
    "创业板50指数": "sz399673",
    "深证100指数": "sz399330",
    "深证成份指数": "sz399001",
    "中证红利指数": "sh000922",
    "证券公司指数": "sz399975",
    "中证酒指数": "sz399987",
    "国证半导体芯片指数": "sz980017",  # 国证芯片（新浪行情代码，注意 399995 是基建工程）
    "芯片指数": "sz980017",  # 基金列表关键词匹配的宽松名，兜底用
}


def extract_management_company(name: str) -> Optional[str]:
    for kw, full_name in COMPANY_KEYWORDS:
        if kw in name:
            return full_name
    return None


def infer_tracking_index(name: str) -> Optional[str]:
    for kw, index_name in INDEX_KEYWORDS:
        if kw in name:
            return index_name
    return None


def infer_industry(tracking_index: Optional[str] = None, name: str = "", fund_type: str = "") -> str:
    """根据跟踪标的名称推断行业分类，兜底采用 ETF 名称关键词匹配。
    优先使用 f10 页面抓取的跟踪标的名（比 ETF 名称更权威、更精确）。
    """
    industry_map = [
        # 行业/主题组（优先匹配，避免被宽基关键词截胡）
        (["半导体", "芯片", "5G", "人工智能", "计算机", "通信", "大数据", "云计算", "电子", "信息技术"], "科技/TMT"),
        (["新能源", "光伏", "新能源汽车", "电池", "碳中和", "电力"], "新能源"),
        (["医药", "医药卫生", "创新药", "中药", "医疗", "生物医药", "医疗器械"], "医药健康"),
        (["银行", "证券", "金融", "保险"], "金融"),
        (["消费", "食品饮料", "白酒", "酒", "家电"], "消费"),
        (["军工", "国防", "航空"], "国防军工"),
        (["房地产", "基建", "建筑"], "地产基建"),
        (["煤炭", "钢铁", "有色金属", "化工", "稀土", "黄金", "石油", "能源"], "资源周期"),
        (["传媒", "游戏", "影视", "动漫"], "传媒娱乐"),
        (["红利"], "红利策略"),
        # 宽基指数组（兜底，优先级低于行业）
        (["沪深300", "上证50", "上证180", "深证100", "中证100"], "大盘蓝筹"),
        (["中证500", "中证800"], "中盘成长"),
        (["中证1000", "中证2000", "国证2000"], "小盘成长"),
        (["科创50", "科创100", "科创创业50", "创业板"], "科技创新"),
    ]

    # 优先匹配跟踪标的（f10 页面抓取，比 ETF 名称精确）
    source = tracking_index or name or ""
    for keywords, industry in industry_map:
        for kw in keywords:
            if kw in source:
                return industry

    # 兜底：跟踪标的不含关键词时再扫 ETF 名称
    if tracking_index and source != (name or ""):
        for keywords, industry in industry_map:
            for kw in keywords:
                if kw in (name or ""):
                    return industry

    return "综合/其他"


# ── 基金列表（缓存 10 分钟）──────────────────────────────────

_fund_list_cache: Optional[dict] = None
_fund_list_cache_time: float = 0
CACHE_TTL = 3600  # 基金列表缓存 1 小时，避免每次冷启动都重新下载 2MB 列表


def fetch_fund_list() -> dict[str, dict]:
    global _fund_list_cache, _fund_list_cache_time

    if _fund_list_cache and (time.time() - _fund_list_cache_time) < CACHE_TTL:
        return _fund_list_cache

    logger.info("正在从东方财富下载全量基金列表...")
    url = "http://fund.eastmoney.com/js/fundcode_search.js"
    req = urllib.request.Request(url, headers=HEADERS_EASTMONEY)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"下载基金列表失败: {e}")
        if _fund_list_cache:
            return _fund_list_cache  # fallback to stale cache
        raise RuntimeError("东方财富数据接口不可用")

    try:
        idx = raw.index("var r = [") + len("var r = [")
        content = raw[idx:-2]
    except ValueError:
        logger.error("基金列表格式解析失败")
        if _fund_list_cache:
            return _fund_list_cache
        raise RuntimeError("东方财富数据格式异常")

    entries = content.split("],[")
    result = {}
    seen = set()

    for i, entry in enumerate(entries):
        if i == 0:
            entry = entry[1:]
        if i == len(entries) - 1:
            entry = entry[:-1]
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
    logger.info(f"基金列表已缓存，共 {len(result)} 只 ETF")
    return result


# ── 基金详情（规模、成立日期）──────────────────────────────

def fetch_fund_detail(code: str) -> dict:
    """并行下载 pingzhongdata（规模）+ f10 概况页（费率/跟踪标的）+ 主页面（跟踪误差）"""
    pz_url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
    f10_url = f"http://fundf10.eastmoney.com/jbgk_{code}.html"
    main_url = f"http://fund.eastmoney.com/{code}.html"

    def _get(url: str, timeout: int) -> str:
        try:
            req = urllib.request.Request(url, headers=HEADERS_EASTMONEY)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"获取 {code} {url} 失败: {e}")
            return ""

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_pz = executor.submit(_get, pz_url, 10)
        f_f10 = executor.submit(_get, f10_url, 10)
        f_main = executor.submit(_get, main_url, 10)
        raw = f_pz.result()
        html = f_f10.result()
        main_html = f_main.result()

    result = {}

    if raw:
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

    # f10 基金概况页：一页同时拿「成立日期 + 管理费率 + 托管费率」
    try:
        # 成立日期在页面上有两种形态：<span>2012-05-04</span> 或 <td>2012年05月04日 / ...</td>
        m_date = re.search(r"成立日期：<span>([^<]+)</span>", html)
        if not m_date:
            m_date = re.search(r"成立日期/规模</th><td>([^<]+)</td>", html)
        if m_date:
            date_str = re.sub(r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"\1-\2-\3", m_date.group(1))
            m_iso = re.search(r"\d{4}-\d{1,2}-\d{1,2}", date_str)
            if m_iso:
                result["established_date"] = m_iso.group(0)

        def _extract_fee_pct(keyword: str) -> Optional[float]:
            m = re.search(re.escape(keyword) + r"</th><td>([^<]+)</td>", html)
            if not m:
                return None
            num = re.search(r"(\d+(?:\.\d+)?)", m.group(1))
            return float(num.group(1)) if num else None

        mgmt_pct = _extract_fee_pct("管理费率")
        custody_pct = _extract_fee_pct("托管费率")
        if mgmt_pct is not None:
            result["management_fee"] = f"{mgmt_pct}%"
        if custody_pct is not None:
            result["custody_fee"] = f"{custody_pct}%"
        if mgmt_pct is not None and custody_pct is not None:
            result["fee_rate"] = f"{round(mgmt_pct + custody_pct, 4)}%"

        # 直接从页面提取跟踪标的（优先于关键词匹配，避免"酒/白酒"混淆）
        # 页面结构: <th>跟踪标的</th><td>中证酒指数</td>
        m_track = re.search(r"跟踪标的</th><td>([^<]+)</td>", html)
        if m_track:
            result["tracking_index"] = m_track.group(1).strip()
    except Exception as e:
        logger.warning(f"获取 {code} f10 概况页失败: {e}")

    # 从主页面抓取年化跟踪误差（格式：跟踪标的：沪深300指数 | 年化跟踪误差：0.35%）
    if main_html:
        m_te = re.search(r'年化跟踪误差[：:]\s*([\d.]+)\s*%', main_html)
        if m_te:
            result["tracking_error"] = float(m_te.group(1)) / 100  # 百分比转小数

    return result


# ── 新浪财经实时快照 ────────────────────────────────────────

def fetch_snapshots(codes: list[str]) -> dict[str, Optional[dict]]:
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
            raw = resp.read().decode("gbk")
    except Exception as e:
        logger.error(f"新浪快照请求失败: {e}")
        return {code: None for code in codes}

    results = {}
    for line in raw.strip().split("\n"):
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
                name = parts[0]
                open_price = float(parts[1]) if parts[1] else None
                prev_close = float(parts[2]) if parts[2] else None
                price = float(parts[3]) if parts[3] else None
                high = float(parts[4]) if parts[4] else None
                low = float(parts[5]) if parts[5] else None
                volume = float(parts[8]) if len(parts) > 8 and parts[8] else None
                amount = float(parts[9]) if len(parts) > 9 and parts[9] else None

                if price is None or prev_close is None or prev_close == 0:
                    results[code] = None
                    continue
                if price <= 0.01:
                    results[code] = None
                    continue
                change_pct = (price - prev_close) / prev_close
                if abs(change_pct) >= 0.30:
                    results[code] = None
                    continue

                results[code] = {
                    "name": name, "price": round(price, 4),
                    "prev_close": round(prev_close, 4),
                    "change_percent": round(change_pct, 6),
                    "open_price": round(open_price, 4) if open_price else None,
                    "high": round(high, 4) if high else None,
                    "low": round(low, 4) if low else None,
                    "volume": volume, "amount": amount,
                }
            except (ValueError, IndexError):
                results[code] = None

    for code in codes:
        if code not in results:
            results[code] = None
    return results


# ── 新浪 K 线历史数据（performance） ─────────────────────────

def resolve_kline_symbol(code: str) -> str:
    if code.startswith(("51", "56", "58")):
        return f"sh{code}"
    if code.startswith(("15", "16")):
        return f"sz{code}"
    return f"sh{code}"


def calculate_returns(kline_data: list[dict]) -> dict[str, Optional[float]]:
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


# ── 指数 K 线与跟踪误差 ───────────────────────────────────────

def fetch_index_kline(symbol: str, days: int = 250) -> Optional[list]:
    """抓取指数日 K 线（新浪接口，返回格式与 ETF K 线一致）"""
    url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&datalen={days}"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS_SINA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk")
        data = json.loads(raw)
        if isinstance(data, list) and len(data) > 0:
            return data
    except Exception as e:
        logger.warning(f"获取指数 {symbol} K 线失败: {e}")
    return None


def calculate_tracking_error(etf_kline: list, index_kline: list) -> Optional[float]:
    """近似跟踪误差（年化）：
    用 ETF 收盘价与指数收盘价逐日收益率之差的年化标准差。
    注意：基于场内价格计算，含折溢价噪声，仅作参考。
    样本不足 20 个交易日时返回 None（新上市 ETF 无跟踪误差）。
    """
    if not etf_kline or not index_kline:
        return None
    if len(etf_kline) < 20 or len(index_kline) < 20:
        return None
    try:
        etf_close = {d["day"]: float(d["close"]) for d in etf_kline}
        index_close = {d["day"]: float(d["close"]) for d in index_kline}
    except (KeyError, ValueError):
        return None

    common_days = sorted(set(etf_close) & set(index_close))
    if len(common_days) < 20:
        return None

    diffs = []
    for prev, cur in zip(common_days, common_days[1:]):
        try:
            if etf_close[prev] == 0 or index_close[prev] == 0:
                continue
            etf_ret = (etf_close[cur] - etf_close[prev]) / etf_close[prev]
            index_ret = (index_close[cur] - index_close[prev]) / index_close[prev]
            diffs.append(etf_ret - index_ret)
        except (KeyError, ValueError):
            continue
    if len(diffs) < 20:
        return None

    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
    annualized = (var ** 0.5) * (252 ** 0.5)
    return round(annualized, 6)


def fetch_etf_nav(code: str) -> Optional[list]:
    """从东方财富 pingzhongdata JS 提取 ETF 每日净值，
    用 equityReturn（已复权日收益率）构建伪收盘价序列，
    返回 [{"day": "2026-08-11", "close": 1.0000}, ...]，兼容 calculate_tracking_error()
    """
    url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
    try:
        req = urllib.request.Request(url, headers=HEADERS_EASTMONEY)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        m = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?\}\s*\]);', raw)
        if not m:
            return None
        data = json.loads(m.group(1))
        tz = timezone(timedelta(hours=8))
        result = []
        prev_close = 1.0
        for item in data:
            ts = item.get("x")
            eq_ret = item.get("equityReturn") or 0  # 已复权的日收益率（%），含拆分红修正
            if not ts:
                continue
            day = datetime.fromtimestamp(ts / 1000, tz).strftime("%Y-%m-%d")
            if eq_ret == 0 and prev_close == 1.0:
                # 第一条数据无前值可比较，记录基础价但不算收益
                result.append({"day": day, "close": prev_close})
                continue
            prev_close *= (1 + eq_ret / 100)
            result.append({"day": day, "close": prev_close})
        return result if len(result) >= 2 else None
    except Exception as e:
        logger.warning(f"获取 {code} 净值数据失败: {e}")
        return None


def _fetch_single_performance(code: str, days: int = 260) -> Optional[dict]:
    """单只 ETF 历史表现。
    跟踪误差直接从东方财富基金详情页抓取（无需 INDEX_CODE_MAP + 指数K线 + 净值计算）。
    """
    kline_symbol = resolve_kline_symbol(code)
    kline_url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={kline_symbol}&scale=240&datalen={days}"
    )

    def _fetch_kline():
        try:
            req = urllib.request.Request(kline_url, headers=HEADERS_SINA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("gbk"))
        except Exception as e:
            logger.warning(f"获取 {code} K 线数据失败: {e}")
            return None

    data = _fetch_kline()
    if not isinstance(data, list) or len(data) == 0:
        return None
    returns = calculate_returns(data)
    if not returns:
        return None
    result = {"name": "", "returns": returns}

    # 从东方财富基金详情页直接抓取年化跟踪误差（无需 INDEX_CODE_MAP + 指数K线 + 净值计算）
    # 页面格式示例：跟踪标的：沪深300指数 | 年化跟踪误差：0.35%
    try:
        main_url = f"http://fund.eastmoney.com/{code}.html"
        req = urllib.request.Request(main_url, headers=HEADERS_EASTMONEY)
        with urllib.request.urlopen(req, timeout=10) as resp:
            main_html = resp.read().decode("utf-8", errors="replace")
        m_te = re.search(r'年化跟踪误差[：:]\s*([\d.]+)\s*%', main_html)
        if m_te:
            result["tracking_error"] = float(m_te.group(1)) / 100  # 百分比转小数
    except Exception:
        pass  # 无跟踪误差数据（新基金等）时保持 None
    return result


def fetch_performances(codes: list[str]) -> dict[str, Optional[dict]]:
    """并发获取多只 ETF 历史表现（适应 Vercel 10s 超时限制）"""
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(codes), 3)) as executor:
        futures = {
            executor.submit(_fetch_single_performance, code, 260): code
            for code in codes
        }
        for future in as_completed(futures, timeout=25):
            code = futures[future]
            try:
                results[code] = future.result()
            except Exception:
                results[code] = None
    return results
