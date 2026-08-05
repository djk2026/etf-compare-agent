"""
GET /api/etf/search?keyword=沪深300 — ETF 模糊搜索
返回匹配的 ETF 列表（代码 + 名称 + 公司），用于前端自动补全
"""
import sys, os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shared import fetch_fund_list


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            keyword = unquote(params.get("keyword", [""])[0]).strip()

            if not keyword:
                self._send_json([])
                return

            fund_list = fetch_fund_list()
            keyword_lower = keyword.lower()
            matches = []

            for code, info in fund_list.items():
                name = info.get("name", "")
                idx = info.get("tracking_index", "") or ""
                company = info.get("management_company", "") or ""

                # Match against: code, name, tracking_index
                score = 0
                if keyword in code:
                    score = 100  # exact code match, highest priority
                elif keyword_lower in name.lower():
                    # name match: shorter name = better match
                    score = 80 - min(len(name), 50)
                elif idx and keyword in idx:
                    score = 60
                elif company and keyword in company:
                    score = 40
                else:
                    continue

                matches.append({
                    "code": code,
                    "name": name,
                    "company": company,
                    "tracking_index": idx,
                    "score": score,
                })

            matches.sort(key=lambda x: x["score"], reverse=True)
            top = matches[:15]

            # Return compact format
            result = [{
                "code": m["code"],
                "name": m["name"],
                "company": m["company"],
                "tracking_index": m["tracking_index"],
            } for m in top]

            self._send_json(result)

        except Exception as e:
            self._send_error(500, f"搜索服务异常: {str(e)}")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors(); self.end_headers(); self.wfile.write(body)

    def _send_error(self, code, message):
        body = json.dumps({"error": message}, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors(); self.end_headers(); self.wfile.write(body)
