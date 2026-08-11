"""
POST /api/etf/basic — ETF 基础信息
数据源：东方财富 fund.eastmoney.com
"""
import sys, os, json
from http.server import BaseHTTPRequestHandler

# Vercel 运行时 `api/etf/` 是当前目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shared import fetch_fund_list, fetch_fund_detail


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(content_length))
            codes = body.get('codes', [])
        except (json.JSONDecodeError, ValueError):
            self._send_error(400, "请求体格式错误，需要 JSON")
            return

        try:
            fund_list = fetch_fund_list()
            results = {}

            for code in codes:
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
                    "established_date": None,
                    "establishment_date": None,
                    "management_fee": None,
                    "custody_fee": None,
                    "fee_rate": None,
                }
                detail = fetch_fund_detail(code)
                if detail:
                    entry["fund_size"] = detail.get("fund_size")
                    entry["established_date"] = detail.get("established_date")
                    entry["establishment_date"] = detail.get("established_date")
                    entry["management_fee"] = detail.get("management_fee")
                    entry["custody_fee"] = detail.get("custody_fee")
                    entry["fee_rate"] = detail.get("fee_rate")
                    # 页面抓取的跟踪标的优先于关键词匹配（东方财富官方数据，避免"酒/白酒"混淆）
                    entry["tracking_index"] = detail.get("tracking_index") or entry["tracking_index"]
                results[code] = entry

            self._send_json(results)
        except Exception as e:
            self._send_error(500, f"数据服务异常: {str(e)}")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code, message):
        body = json.dumps({"error": message}, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(body)
