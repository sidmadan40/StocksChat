"""Trading system module for StocksChat."""

from .sentiment import analyze_sentiment, test_gemini_connection
from .news import get_news, fetch_latest_news
from .hmm_model import HMMModel, fit_hmm_model, predict_with_hmm, get_market_regime
from .strategy import (
    TradingStrategy,
    execute_strategy,
    generate_trade_decision,
    reset_daily_trade_count,
    get_capital_per_trade,
    register_trade_execution,
)
from .alpaca_client import (
    AlpacaClient,
    get_alpaca_positions,
    place_trade,
    get_portfolio,
    test_alpaca_connection
)
from .scheduler import (
    TradingScheduler,
    start_trading_scheduler,
    stop_trading_scheduler,
    run_trading_cycle,
    schedule_trading_cycles,
    reset_trading_cycle_count
)

__all__ = [
    "analyze_sentiment",
    "test_gemini_connection",
    "get_news",
    "fetch_latest_news",
    "HMMModel",
    "fit_hmm_model",
    "predict_with_hmm",
    "get_market_regime",
    "TradingStrategy",
    "execute_strategy",
    "generate_trade_decision",
    "reset_daily_trade_count",
    "get_capital_per_trade",
    "register_trade_execution",
    "AlpacaClient",
    "get_alpaca_positions",
    "place_trade",
    "get_portfolio",
    "test_alpaca_connection",
    "TradingScheduler",
    "start_trading_scheduler",
    "stop_trading_scheduler",
    "run_trading_cycle",
    "schedule_trading_cycles",
    "reset_trading_cycle_count",
]
