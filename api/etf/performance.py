"""
POST /api/etf/performance — ETF 历史表现（并发请求，适配 Vercel 10s 超时）
数据源：新浪财经 K 线接口
"""
import sys, os, json
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shared import fetch_performances


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
            performances = fetch_performances(codes)
            results = {}

            for code in codes:
                data = performances.get(code)
                if data is None:
                    results[code] = {
                        "code": code, "name": None, "returns": None,
                        "error": "performance_unavailable",
                        "message": f"ETF {code} 历史数据暂不可用",
                    }
                else:
                    results[code] = {
                        "code": code,
                        "name": data.get("name"),
                        "returns": data.get("returns"),
                    }

            self._send_json(results)
        except Exception as e:
            self._send_error(500, f"数据服务异常: {str(e)}")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
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
