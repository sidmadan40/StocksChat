"""Universe construction and screening utilities for automated trading."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Iterable, List
import json
import re

import pandas as pd
import requests
import yfinance as yf


CACHE_FILE = Path(__file__).resolve().parents[1] / "data" / "trading_universe.json"
CACHE_TTL = timedelta(hours=24)

FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "NFLX",
    "JPM", "V", "MA", "XOM", "LLY", "UNH", "COST", "HD",
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "ULVR.L", "AZN.L", "BP.L", "GSK.L", "HSBA.L",
]

SOURCE_CONFIGS = [
    {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "columns": ["Symbol"],
        "suffix": "",
    },
    {
        "url": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "columns": ["Ticker", "Ticker symbol", "Symbol"],
        "suffix": "",
    },
    {
        "url": "https://en.wikipedia.org/wiki/NIFTY_50",
        "columns": ["Symbol", "Ticker", "Company Name"],
        "suffix": ".NS",
    },
    {
        "url": "https://en.wikipedia.org/wiki/FTSE_100_Index",
        "columns": ["EPIC", "Ticker", "Symbol"],
        "suffix": ".L",
    },
]

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def _normalize_symbol(symbol: str, suffix: str = "") -> str:
    cleaned = (symbol or "").strip().upper().replace(".", "-")
    cleaned = re.sub(r"[^A-Z0-9\-]", "", cleaned)
    if not cleaned:
        return ""
    if suffix and not cleaned.endswith(suffix):
        cleaned = f"{cleaned}{suffix}"
    return cleaned


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _extract_symbols_from_tables(url: str, columns: List[str], suffix: str) -> List[str]:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
    except Exception:
        return []

    for table in tables:
        for column in columns:
            if column not in table.columns:
                continue
            symbols = [_normalize_symbol(str(value), suffix=suffix) for value in table[column].tolist()]
            symbols = [symbol for symbol in symbols if symbol]
            if symbols:
                return _dedupe(symbols)

    return []


def _load_cached_universe() -> List[str]:
    try:
        if not CACHE_FILE.exists():
            return []

        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8") or "{}")
        if not isinstance(payload, dict):
            return []

        created_at = payload.get("created_at")
        symbols = payload.get("symbols", [])
        if not created_at or not isinstance(symbols, list):
            return []

        if datetime.now() - datetime.fromisoformat(created_at) > CACHE_TTL:
            return []

        return _dedupe(str(symbol).upper() for symbol in symbols)
    except Exception:
        return []


def _save_cached_universe(symbols: List[str]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps({"created_at": datetime.now().isoformat(), "symbols": symbols}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_trading_universe(max_tickers: int = 700) -> List[str]:
    """Return a broad tradable universe built from major public index constituents."""
    cached = _load_cached_universe()
    if cached:
        return cached[:max_tickers]

    symbols: List[str] = []
    for config in SOURCE_CONFIGS:
        symbols.extend(
            _extract_symbols_from_tables(
                url=config["url"],
                columns=config["columns"],
                suffix=config["suffix"],
            )
        )

    symbols = _dedupe(symbols)
    if not symbols:
        symbols = FALLBACK_UNIVERSE[:]

    _save_cached_universe(symbols)
    return symbols[:max_tickers]


def _extract_ticker_frame(downloaded: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if downloaded.empty:
        return pd.DataFrame()

    if isinstance(downloaded.columns, pd.MultiIndex):
        if ticker not in downloaded.columns.get_level_values(0):
            return pd.DataFrame()
        return downloaded[ticker].dropna(how="all")

    return downloaded.dropna(how="all")


def screen_trade_candidates(universe: List[str], shortlist_size: int = 12) -> List[str]:
    """Screen a broad universe down to the strongest recent movers for deep analysis."""
    tickers = _dedupe(universe)[:700]
    if not tickers:
        return FALLBACK_UNIVERSE[:shortlist_size]

    try:
        downloaded = yf.download(
            tickers=tickers,
            period="1mo",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception:
        return tickers[:shortlist_size]

    scored = []
    for ticker in tickers:
        frame = _extract_ticker_frame(downloaded, ticker)
        if frame.empty or "Close" not in frame:
            continue

        close = frame["Close"].dropna()
        if len(close) < 10:
            continue

        volume = frame["Volume"].dropna() if "Volume" in frame else pd.Series(dtype=float)
        return_5d = float(close.iloc[-1] / close.iloc[-6] - 1)
        return_1m = float(close.iloc[-1] / close.iloc[0] - 1)
        avg_dollar_volume = 0.0
        if not volume.empty:
            tail_count = min(len(volume), len(close), 5)
            avg_dollar_volume = float((close.tail(tail_count) * volume.tail(tail_count)).mean())

        score = abs(return_5d) * 0.7 + abs(return_1m) * 0.3
        scored.append(
            {
                "ticker": ticker,
                "score": score,
                "avg_dollar_volume": avg_dollar_volume,
            }
        )

    if not scored:
        return tickers[:shortlist_size]

    ranked = sorted(
        scored,
        key=lambda item: (item["score"], item["avg_dollar_volume"]),
        reverse=True,
    )
    return [item["ticker"] for item in ranked[:shortlist_size]]
