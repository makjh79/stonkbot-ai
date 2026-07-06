"""STONK.AI Real-time Monitor & Alert System v1.0

Checks:
  - systemd services are running
  - data freshness (signals, portfolio, watchlist)
  - portfolio drawdown (kill switch at -15% daily)
  - disk space, rogue processes, permissions

Outputs:
  - Logs to /opt/stonk-ai/monitor.log
  - Sends Telegram alert if enabled
  - Writes /opt/stonk-ai/monitor_status.json
"""

import argparse
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/opt/stonk-ai/monitor.log"),
        logging.StreamHandler(),
    ],
)

BASE = Path(__file__).resolve().parent

# Telegram bot config (read from env or config file)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Services to monitor
SERVICES = [
    "stonk-ai.service",
    "stonk-ai-data.service",
    "stonk-ai-watchlist.service",
    "stonk-ai-markets.service",
]

# Data files and max age (minutes) — market hours vs closed
MARKET_HOURS_MAX_AGE = {
    "signals.json": 30,
    "popup_content.json": 10,
    "portfolio_data.json": 10,
    "ai_watchlist_live.json": 30,
}
CLOSED_MAX_AGE = {
    "signals.json": 480,
    "popup_content.json": 30,
    "portfolio_data.json": 30,
    "ai_watchlist_live.json": 480,
}

# Kill switch threshold
KILL_SWITCH_DAILY_DRAWDOWN = -0.15


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)

    def send(self, message: str):
        if not self.enabled:
            logger.info(f"[ALERT] {message}")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")


class SystemMonitor:
    def __init__(self):
        self.alerts: List[str] = []
        self.status = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "services": {},
            "data_freshness": {},
            "portfolio": {},
            "disk": {},
            "rogue_processes": [],
            "permissions": [],
            "kill_switch_triggered": False,
            "healthy": True,
        }
        self.alerter = TelegramAlerter(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    def _run(self, cmd: List[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception as e:
            return f"error: {e}"

    # ------------------------------------------------------------------
    # Service checks
    # ------------------------------------------------------------------

    def check_services(self):
        for service in SERVICES:
            status = self._run(["systemctl", "is-active", service])
            self.status["services"][service] = status
            if status != "active":
                self.alerts.append(f"Service {service} is {status}")
                self.status["healthy"] = False

    # ------------------------------------------------------------------
    # Data freshness
    # ------------------------------------------------------------------

    @staticmethod
    def is_market_open() -> bool:
        now = datetime.now(timezone.utc)
        year = now.year
        march_8 = datetime(year, 3, 8, tzinfo=timezone.utc)
        mar_dst = march_8 + timedelta(days=(6 - march_8.weekday()))
        nov_1 = datetime(year, 11, 1, tzinfo=timezone.utc)
        nov_dst = nov_1 + timedelta(days=(6 - nov_1.weekday()))
        utc_offset = -4 if mar_dst <= now < nov_dst else -5
        if now.weekday() >= 5:
            return False
        et_hour = now.hour + (now.minute / 60) + utc_offset
        return 9.5 <= et_hour < 16.0

    def _get_max_age(self, filename: str) -> int:
        now = datetime.now(timezone.utc)
        if self.is_market_open():
            return MARKET_HOURS_MAX_AGE.get(filename, 30)
        if now.weekday() >= 5 or (now.weekday() == 4 and now.hour >= 20) or (now.weekday() == 0 and now.hour < 13):
            if filename in ("signals.json", "ai_watchlist_live.json"):
                return 2880
        return CLOSED_MAX_AGE.get(filename, 60)

    def check_data_freshness(self):
        now = datetime.now(timezone.utc)
        for filename in MARKET_HOURS_MAX_AGE:
            max_age_min = self._get_max_age(filename)
            path = BASE / filename
            if not path.exists():
                self.alerts.append(f"Missing data file: {filename}")
                self.status["data_freshness"][filename] = {"status": "missing"}
                self.status["healthy"] = False
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age_min = (now - mtime).total_seconds() / 60
            self.status["data_freshness"][filename] = {"age_minutes": age_min, "max_age_minutes": max_age_min}
            if age_min > max_age_min:
                self.alerts.append(f"Stale data: {filename} is {age_min:.0f} min old")
                self.status["healthy"] = False

    # ------------------------------------------------------------------
    # Portfolio / kill switch
    # ------------------------------------------------------------------

    def check_portfolio(self):
        path = BASE / "portfolio_data.json"
        if not path.exists():
            self.alerts.append("No portfolio_data.json for kill-switch check")
            self.status["healthy"] = False
            return
        try:
            data = json.loads(path.read_text())
            pv = data.get("account", {}).get("portfolio_value", 0)
            initial = data.get("initial_value", 100_000.0)
            daily_return = (pv - initial) / initial
            self.status["portfolio"] = {
                "portfolio_value": pv,
                "daily_return": daily_return,
                "kill_switch_threshold": KILL_SWITCH_DAILY_DRAWDOWN,
            }
            if daily_return <= KILL_SWITCH_DAILY_DRAWDOWN:
                self.status["kill_switch_triggered"] = True
                self.status["healthy"] = False
                self.alerts.append(f"KILL SWITCH: portfolio down {daily_return:.1%} today")
        except Exception as e:
            self.alerts.append(f"Portfolio check failed: {e}")
            self.status["healthy"] = False

    # ------------------------------------------------------------------
    # Disk space
    # ------------------------------------------------------------------

    def check_disk(self):
        try:
            usage = self._run(["df", "-h", "/opt/stonk-ai"])
            lines = usage.splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    self.status["disk"] = {
                        "size": parts[1],
                        "used": parts[2],
                        "available": parts[3],
                        "use_pct": parts[4],
                    }
                    use_pct = int(parts[4].rstrip("%"))
                    if use_pct > 85:
                        self.alerts.append(f"Disk usage high: {use_pct}%")
                        self.status["healthy"] = False
        except Exception as e:
            self.alerts.append(f"Disk check failed: {e}")

    # ------------------------------------------------------------------
    # Rogue processes
    # ------------------------------------------------------------------

    def check_rogue_processes(self):
        try:
            ps = self._run(["pgrep", "-a", "-f", "trading_bot.py|fetch_data_simple.py|fetch_ai_watchlist.py"])
            lines = [l for l in ps.splitlines() if l.strip()]
            root_processes = []
            for line in lines:
                pid = line.split()[0]
                user = self._run(["ps", "-o", "user=", "-p", pid])
                if user.strip() == "root":
                    root_processes.append(line)
            self.status["rogue_processes"] = root_processes
            if root_processes:
                self.alerts.append(f"Rogue root processes: {len(root_processes)}")
                self.status["healthy"] = False
        except Exception as e:
            self.alerts.append(f"Rogue process check failed: {e}")

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def check_permissions(self):
        bad = []
        for f in ["signals.json", "portfolio_data.json", "ai_watchlist_live.json"]:
            path = BASE / f
            if not path.exists():
                continue
            try:
                import pwd
                stat = path.stat()
                owner = pwd.getpwuid(stat.st_uid).pw_name
                if owner != "stonkai":
                    bad.append(f"{f} owned by {owner}")
            except Exception:
                pass
        self.status["permissions"] = bad
        if bad:
            self.alerts.append(f"Permission issues: {bad}")
            self.status["healthy"] = False

    # ------------------------------------------------------------------
    # Data quality / schema checks
    # ------------------------------------------------------------------

    def check_data_quality(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        issues_before = len(self.alerts)

        def _report(msg):
            self.alerts.append(msg)
            self.status["healthy"] = False

        # 1. Watchlist data (use web copy, it has merged/enriched fields)
        wl_path = Path("/var/www/hedge-fund-website/ai_watchlist_live.json")
        if wl_path.exists():
            try:
                wl = json.loads(wl_path.read_text())
                prices = wl.get("prices", {})
                for sym, data in prices.items():
                    company = data.get("company", "")
                    if not company or company == sym:
                        _report(f"Data quality: watchlist entry {sym} has bare company name")
                    if "signal_tier" not in data:
                        _report(f"Data quality: watchlist entry {sym} missing signal_tier")
                    elif data.get("signal_tier") not in ("STRONG_NOW", "NOW", "WATCH", "MONITOR"):
                        _report(f"Data quality: watchlist entry {sym} unexpected signal_tier: {data.get('signal_tier')}")
                    price = data.get("price")
                    if price is None or price <= 0 or price > 50000:
                        _report(f"Data quality: watchlist entry {sym} suspicious price: {price}")
                    rsi = data.get("rsi")
                    if rsi is not None and (rsi < 0 or rsi > 100):
                        _report(f"Data quality: watchlist entry {sym} invalid RSI: {rsi}")

                if prices and all(d.get("signal_tier") == "MONITOR" for d in prices.values()):
                    _report("Data quality: all watchlist entries are MONITOR (possible tier mapping bug)")
            except Exception as e:
                _report(f"Data quality: failed to parse ai_watchlist_live.json: {e}")

        # 2. Popup content
        popup_path = BASE / "popup_content.json"
        if popup_path.exists():
            try:
                popup = json.loads(popup_path.read_text())
                for sym, pdata in list(popup.get("holdings", {}).items())[:10]:
                    if pdata.get("company") == sym or not pdata.get("company"):
                        _report(f"Data quality: popup holding {sym} has bare company name")
            except Exception as e:
                _report(f"Data quality: failed to parse popup_content.json: {e}")

        # 3. Frontend schema drift
        html_path = Path("/var/www/hedge-fund-website/index.html")
        if html_path.exists():
            try:
                html = html_path.read_text()
                if "stock.signal === 'STRONG_NOW'" in html or "stock.signal === 'NOW'" in html:
                    _report("Schema drift: index.html references stock.signal for watchlist tiers (should be signal_tier)")
                # Check tierOrder completeness
                tier_order_match = re.search(r"const tierOrder =\s*\{([^}]+)\}\s*;", html)
                if tier_order_match:
                    tiers_found = set(re.findall(r"'([A-Z_]+)'\s*:", tier_order_match.group(1)))
                    required_tiers = {"STRONG_NOW", "NOW", "WATCH", "MONITOR"}
                    missing = required_tiers - tiers_found
                    if missing:
                        _report(f"Schema drift: tierOrder sort mapping missing {missing} in index.html")
                else:
                    _report("Schema drift: tierOrder definition not found in index.html")
            except Exception:
                pass

        self.status["data_quality"] = {
            "checked_at": now.isoformat(),
            "issues_found": len(self.alerts) - issues_before,
        }

    def run(self) -> Dict:
        self.check_services()
        self.check_data_freshness()
        self.check_portfolio()
        self.check_disk()
        self.check_rogue_processes()
        self.check_permissions()
        self.check_data_quality()

        if self.alerts:
            parts = ["STONK.AI Monitor Alerts:"] + [f"- {a}" for a in self.alerts]
            summary = "\\n".join(parts)
            self.alerter.send(summary)
        else:
            logger.info("All checks passed.")

        out = BASE / "monitor_status.json"
        out.write_text(json.dumps(self.status, indent=2, default=str))
        logger.info(f"Monitor status saved to {out}")
        return self.status


def main():
    parser = argparse.ArgumentParser(description="STONK.AI Monitor")
    parser.add_argument("--alert", action="store_true", help="Send Telegram alert even if healthy")
    args = parser.parse_args()

    monitor = SystemMonitor()
    status = monitor.run()

    if args.alert and not monitor.alerts:
        monitor.alerter.send("STONK.AI monitor: all checks passed.")

    print(json.dumps(status, indent=2, default=str))


if __name__ == "__main__":
    main()