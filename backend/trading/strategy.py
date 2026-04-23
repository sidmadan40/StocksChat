"""Trading strategy implementation."""

from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import yfinance as yf


# Global trade counter for daily limit
_daily_trades = {
    "date": datetime.now().date(),
    "count": 0,
    "max_per_day": 5,
    "capital_per_trade": 1.0 / 5  # Equal allocation
}


@dataclass
class TradeSignal:
    ticker: str
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float
    reason: str
    price_target: Optional[float] = None


class TradingStrategy:
    """Base trading strategy class."""
    
    def __init__(self, name: str):
        self.name = name
        self.trades: List[TradeSignal] = []
    
    def evaluate(self, ticker: str, data: Dict) -> TradeSignal:
        """
        Evaluate a stock and generate trading signal.
        
        Args:
            ticker: Stock ticker symbol
            data: Stock data (price, indicators, etc.)
        
        Returns:
            TradeSignal with action and confidence
        """
        return TradeSignal(
            ticker=ticker,
            action="HOLD",
            confidence=0.5,
            reason="No signal"
        )
    
    def add_trade(self, signal: TradeSignal):
        """Record a trade signal."""
        self.trades.append(signal)
    
    def get_trades(self) -> List[TradeSignal]:
        """Get all recorded trades."""
        return self.trades


class HMMTradingStrategy(TradingStrategy):
    """Trading strategy using HMM for market state."""
    
    def __init__(self):
        super().__init__("HMM Trading Strategy")
        self.model = None
    
    def evaluate(self, ticker: str, hmm_state: int, hmm_confidence: float) -> TradeSignal:
        """
        Generate trading signal based on HMM market state.
        
        Args:
            ticker: Stock ticker symbol
            hmm_state: Current HMM state (0=bear, 1=normal, 2=bull)
            hmm_confidence: Confidence score
        
        Returns:
            TradeSignal
        """
        action_map = {
            0: "SELL",    # Bear market
            1: "HOLD",    # Normal market
            2: "BUY"      # Bull market
        }
        
        action = action_map.get(hmm_state, "HOLD")
        
        return TradeSignal(
            ticker=ticker,
            action=action,
            confidence=hmm_confidence,
            reason=f"HMM state {hmm_state}: {action}"
        )


def execute_strategy(strategy: TradingStrategy, tickers: List[str], data: Dict) -> List[TradeSignal]:
    """
    Execute trading strategy on multiple tickers.
    
    Args:
        strategy: TradingStrategy instance
        tickers: List of ticker symbols
        data: Market data
    
    Returns:
        List of TradeSignals
    """
    signals = []
    for ticker in tickers:
        try:
            signal = strategy.evaluate(ticker, data)
            strategy.add_trade(signal)
            signals.append(signal)
        except Exception as e:
            print(f"Strategy evaluation error for {ticker}: {e}")
    
    return signals


def reset_daily_trade_count():
    """Reset daily trade counter (call at market open)."""
    global _daily_trades
    _daily_trades["date"] = datetime.now().date()
    _daily_trades["count"] = 0


def get_capital_per_trade() -> float:
    """Get capital allocation per trade."""
    return _daily_trades["capital_per_trade"]


def register_trade_execution() -> None:
    """Increment the daily trade counter after a real trade is executed."""
    global _daily_trades

    today = datetime.now().date()
    if _daily_trades["date"] < today:
        reset_daily_trade_count()

    _daily_trades["count"] += 1


def generate_trade_decision(sentiment: Dict, regime: Dict, track_trade: bool = True) -> Dict:
    """
    Generate trading decision based on sentiment and market regime.
    
    Args:
        sentiment: Dict with keys "score" (-1 to 1), "label" (negative/neutral/positive)
        regime: Dict with keys "regime" (bull/bear/neutral), "confidence" (0-1)
        track_trade: Increment daily trade counter when a BUY/SELL signal is produced.
    
    Returns:
        dict with:
        - action: "BUY", "SELL", or "HOLD"
        - confidence: float (0-1)
        - reason: str
        - capital_allocation: float (portfolio % to allocate)
    """
    global _daily_trades
    
    try:
        # Reset counter if new day
        today = datetime.now().date()
        if _daily_trades["date"] < today:
            reset_daily_trade_count()
        
        # Extract values with defaults
        sentiment_score = sentiment.get("score", 0.0)
        sentiment_label = sentiment.get("label", "neutral").lower()
        regime_type = regime.get("regime", "neutral").lower()
        regime_conf = regime.get("confidence", 0.0)
        
        # Clamp values to valid ranges
        sentiment_score = max(-1.0, min(1.0, sentiment_score))
        regime_conf = max(0.0, min(1.0, regime_conf))
        
        # Check daily trade limit
        can_trade = _daily_trades["count"] < _daily_trades["max_per_day"]
        
        # Decision logic
        is_bullish = regime_type == "bull"
        is_bearish = regime_type == "bear"
        is_positive_sentiment = sentiment_label in ["positive", "bullish"] and sentiment_score > 0.3
        is_negative_sentiment = sentiment_label in ["negative", "bearish"] and sentiment_score < -0.3
        
        # Primary decision
        if can_trade and is_bullish and is_positive_sentiment:
            action = "BUY"
            confidence = min(1.0, (regime_conf + (sentiment_score + 1) / 2) / 2)
            reason = f"Bull regime ({regime_conf:.2f}) + positive sentiment ({sentiment_score:.2f})"
        elif is_bearish or is_negative_sentiment:
            action = "SELL"
            confidence = min(1.0, (regime_conf + (abs(sentiment_score)) / 2) / 2) if is_bearish else abs(sentiment_score)
            reason = f"Bear regime ({regime_conf:.2f})" if is_bearish else f"Negative sentiment ({sentiment_score:.2f})"
        else:
            action = "HOLD"
            confidence = 0.5
            reason = f"Neutral setup: {regime_type} + {sentiment_label} sentiment"
        
        # Apply daily trade limit
        if action in ["BUY", "SELL"] and not can_trade:
            action = "HOLD"
            reason = f"Daily trade limit ({_daily_trades['max_per_day']}) reached"
            confidence = 0.3
        
        # Track trade
        if action in ["BUY", "SELL"] and track_trade:
            _daily_trades["count"] += 1
        
        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "capital_allocation": get_capital_per_trade() if action in ["BUY", "SELL"] else 0.0,
            "daily_trades_used": _daily_trades["count"],
            "daily_trades_max": _daily_trades["max_per_day"]
        }
    
    except Exception as e:
        return {
            "action": "HOLD",
            "confidence": 0.0,
            "reason": f"Decision error: {str(e)[:100]}",
            "capital_allocation": 0.0,
            "daily_trades_used": _daily_trades["count"],
            "daily_trades_max": _daily_trades["max_per_day"]
        }
