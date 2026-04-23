"""Temporary runner for one AI trade cycle."""

from backend.trading.scheduler import run_ai_trade_cycle


if __name__ == "__main__":
    run_ai_trade_cycle()