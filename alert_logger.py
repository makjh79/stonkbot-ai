import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ALERT_LOG = Path('/opt/stonk-ai/alert_log.json')
WEB_ALERT_LOG = Path('/var/www/hedge-fund-website/alert_log.json')


def log_alert(
    subtype: str,
    title: str,
    description: str,
    symbol: Optional[str] = None,
    value: Optional[float] = None,
    value_label: Optional[str] = None,
    severity: str = "info",
    rationale: Optional[str] = None,
    bot_response: Optional[str] = None,
) -> dict:
    """Append a bot-generated alert to alert_log.json for the website activity feed."""
    try:
        data = {"alerts": []}
        if ALERT_LOG.exists():
            data = json.loads(ALERT_LOG.read_text())

        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "type": "alert",
            "subtype": subtype,
            "severity": severity,
            "title": title,
            "description": description,
            "symbol": symbol,
            "value": value,
            "value_label": value_label,
            "rationale": rationale or description,
            "bot_response": bot_response or "System recorded this event for monitoring.",
        }
        data.setdefault("alerts", []).append(alert)
        data["alerts"] = data["alerts"][-200:]
        data["last_updated"] = alert["timestamp"]

        ALERT_LOG.write_text(json.dumps(data, indent=2))
        WEB_ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
        WEB_ALERT_LOG.write_text(json.dumps(data, indent=2))
        return alert
    except Exception:
        return {}


def load_alerts(limit: int = 200) -> List[dict]:
    try:
        if ALERT_LOG.exists():
            data = json.loads(ALERT_LOG.read_text())
            return data.get("alerts", [])[-limit:]
    except Exception:
        pass
    return []
