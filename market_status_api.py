#!/usr/bin/env python3
"""Tiny HTTP endpoint: /api/market-status - returns Alpaca clock as JSON."""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests

ALPACA_CONFIG = Path(os.environ.get("STONKBOT_ALPACA_CONFIG", "/opt/stonk-ai/alpaca_config.json"))

with open(ALPACA_CONFIG) as f:
    _cfg = json.load(f)

_ALPACA_KEY = _cfg["api_key"]
_ALPACA_SECRET = _cfg["api_secret"]
_ALPACA_URL = _cfg.get("base_url", "https://paper-api.alpaca.markets").rstrip("/") + "/v2/clock"

def _get_clock():
    resp = requests.get(
        _ALPACA_URL,
        headers={
            "APCA-API-KEY-ID": _ALPACA_KEY,
            "APCA-API-SECRET-KEY": _ALPACA_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path not in ("/api/market-status", "/api/market-status/"):
            self.send_error(404)
            return
        try:
            data = _get_clock()
            body = json.dumps({
                "is_open": bool(data.get("is_open")),
                "next_open": data.get("next_open"),
                "next_close": data.get("next_close"),
                "timestamp": data.get("timestamp"),
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body.encode())
        except Exception as exc:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

if __name__ == "__main__":
    port = int(os.environ.get("MARKET_STATUS_PORT", "8081"))
    srv = HTTPServer(("127.0.0.1", port), _Handler)
    print(f"[market-status] Listening on 127.0.0.1:{port}", flush=True)
    srv.serve_forever()
