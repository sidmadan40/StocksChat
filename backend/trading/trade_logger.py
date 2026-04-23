"""Trade logging utilities for persistent trade records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import json


TRADES_FILE = Path(__file__).resolve().parents[1] / "data" / "trades.json"


def _ensure_trades_file() -> None:
    """Create trades.json if it does not exist."""
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TRADES_FILE.exists():
        TRADES_FILE.write_text("[]\n", encoding="utf-8")


def _read_entries() -> List[Dict[str, Any]]:
    """Read existing trade entries safely."""
    _ensure_trades_file()
    try:
        raw = json.loads(TRADES_FILE.read_text(encoding="utf-8") or "[]")
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        return []
    except Exception:
        return []


def _build_entry(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize incoming data into the required trade log schema."""
    decision = data.get("decision", {})
    action = data.get("action", decision.get("action", "HOLD"))
    quantity = data.get("quantity", data.get("qty", 0))

    return {
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
        "ticker": data.get("ticker", ""),
        "sentiment": data.get("sentiment", {}),
        "regime": data.get("regime", {}),
        "decision": decision,
        "action": action,
        "quantity": quantity,
        "explanation": data.get("explanation", ""),
    }


def log_trade(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append a trade record to trades.json (without overwriting prior entries).

    Required stored fields:
    {
      timestamp,
      ticker,
      sentiment,
      regime,
      decision,
      action,
            quantity,
            explanation
    }
    """
    try:
        entries = _read_entries()
        entries.append(_build_entry(data or {}))
        TRADES_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return {"status": "success", "entries": len(entries), "file": str(TRADES_FILE)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}