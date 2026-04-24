"""APScheduler integration for automated trading."""

from typing import Callable, List, Optional, Dict
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import yfinance as yf
from datetime import datetime, time
from pathlib import Path
import json
from zoneinfo import ZoneInfo

# Import trading functions
from backend.trading.news import get_news
from backend.trading.sentiment import analyze_sentiment
from backend.trading.hmm_model import get_market_regime
from backend.trading.strategy import generate_trade_decision, register_trade_execution
from backend.trading.alpaca_client import place_trade, get_portfolio as get_live_portfolio
from backend.trading.trade_logger import log_trade
from backend.trading.universe import load_trading_universe, screen_trade_candidates
from backend.gemini_client import get_gemini_client, select_gemini_model


logger = logging.getLogger(__name__)


STATE_FILE = Path(__file__).resolve().parents[1] / "data" / "trading_cycle_state.json"
NYSE_TZ = ZoneInfo("America/New_York")
NYSE_OPEN = time(hour=9, minute=30)
NYSE_CLOSE = time(hour=16, minute=0)


def _default_state() -> Dict:
    return {
        "hour_bucket": "",
        "executions": 0,
        "max_per_hour": 6,
    }


def _load_state() -> Dict:
    """Load persisted hourly execution state."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not STATE_FILE.exists():
            state = _default_state()
            STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
            return state

        raw = json.loads(STATE_FILE.read_text(encoding="utf-8") or "{}")
        state = _default_state()
        if isinstance(raw, dict):
            state.update(raw)
        state["executions"] = int(state.get("executions", 0) or 0)
        state["max_per_hour"] = int(state.get("max_per_hour", raw.get("max_per_day", 6)) or 6)
        state["hour_bucket"] = str(state.get("hour_bucket", "") or "")
        return state
    except Exception:
        return _default_state()


def _save_state(state: Dict) -> None:
    """Persist hourly execution state."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to persist trading cycle state: {e}")


def _get_position_tickers() -> List[str]:
    """Return tickers currently held in the live portfolio so sells are always considered."""
    try:
        portfolio = get_live_portfolio()
        if "error" in portfolio:
            return []
        return [position.get("ticker", "") for position in portfolio.get("positions", []) if position.get("ticker")]
    except Exception:
        return []


def _dedupe_tickers(tickers: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for ticker in tickers:
        if ticker and ticker not in seen:
            seen.add(ticker)
            ordered.append(ticker)
    return ordered


def evaluate_trade_candidate(ticker: str) -> Dict:
    """Analyze one ticker without placing a trade or consuming the daily trade counter."""
    trade_status: Dict = {"status": "not_executed", "reason": "Candidate evaluation only"}

    try:
        headlines = get_news(ticker)
        sentiment = analyze_sentiment(headlines)
        price_series = yf.Ticker(ticker).history(period="1mo")["Close"].values
        prices = price_series.tolist() if hasattr(price_series, "tolist") else list(price_series)
        regime = get_market_regime(prices)
        decision = generate_trade_decision(sentiment, regime, track_trade=False)
        explanation = generate_trade_explanation(
            ticker=ticker,
            action=decision.get("action", "HOLD"),
            sentiment=sentiment,
            regime=regime,
            headlines=headlines,
        )

        return {
            "ticker": ticker,
            "headlines": headlines,
            "sentiment": sentiment,
            "regime": regime,
            "decision": decision,
            "explanation": explanation,
            "trade_status": trade_status,
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "error": str(e)[:200],
            "trade_status": trade_status,
        }


def select_best_trade_candidate(candidate_tickers: List[str]) -> Dict:
    """Choose the strongest candidate from the screened universe."""
    best_result: Optional[Dict] = None
    best_score = (-1, -1.0)

    for ticker in candidate_tickers:
        result = evaluate_trade_candidate(ticker)
        if result.get("error"):
            logger.warning(f"Candidate evaluation failed for {ticker}: {result.get('error')}")
            continue

        decision = result.get("decision", {})
        action = decision.get("action", "HOLD")
        confidence = float(decision.get("confidence", 0.0) or 0.0)
        action_priority = 1 if action in {"BUY", "SELL"} else 0
        score = (action_priority, confidence)

        if score > best_score:
            best_score = score
            best_result = result

    return best_result or {
        "ticker": candidate_tickers[0] if candidate_tickers else "",
        "error": "No valid trade candidates found",
        "trade_status": {"status": "not_executed", "reason": "No valid trade candidates found"},
    }


def run_ai_trade_cycle() -> Dict:
    """
    Standalone AI trade cycle with broad-universe screening and full debug output.

    Steps:
    1. Build a broad trading universe from major public market constituents
    2. Screen recent movers across that universe
    3. Always include current live positions in the final shortlist
    4. Deep-analyze the shortlist with news, sentiment, regime detection, and decision logic
    5. Execute the best BUY/SELL candidate if one is found
    """
    trade_status: Dict = {"status": "not_executed", "reason": "No decision yet"}

    try:
        base_universe = load_trading_universe()
        screened_tickers = screen_trade_candidates(base_universe, shortlist_size=12)
        position_tickers = _get_position_tickers()
        candidate_tickers = _dedupe_tickers(position_tickers + screened_tickers)

        candidate = select_best_trade_candidate(candidate_tickers)
        if candidate.get("error"):
            raise RuntimeError(candidate["error"])

        ticker = candidate.get("ticker", "")
        headlines = candidate.get("headlines", [])
        sentiment = candidate.get("sentiment", {})
        regime = candidate.get("regime", {})
        decision = candidate.get("decision", {})
        explanation = candidate.get("explanation", "")

        # 5) Log the decision before any broker call for auditability.
        quantity = 1 if decision.get("action") != "HOLD" else 0
        log_trade({
            "ticker": ticker,
            "sentiment": sentiment,
            "regime": regime,
            "decision": decision,
            "action": decision.get("action", "HOLD"),
            "quantity": quantity,
            "explanation": explanation,
        })

        # 6) Place trade if not HOLD
        if decision.get("action") != "HOLD":
            trade_status = place_trade(ticker, decision.get("action", "HOLD"), qty=1)
            if trade_status.get("status") == "success":
                register_trade_execution()
        else:
            trade_status = {
                "status": "skipped",
                "reason": "Decision action is HOLD",
                "action": "HOLD"
            }

        # Log execution result as a separate event for traceability.
        log_trade({
            "ticker": ticker,
            "sentiment": sentiment,
            "regime": regime,
            "decision": decision,
            "action": decision.get("action", "HOLD"),
            "quantity": quantity,
            "explanation": f"{explanation}\nExecution status: {trade_status.get('status', 'unknown')}",
        })

        # 7) Full debug output
        print("===== AI TRADE CYCLE DEBUG =====")
        print(f"Universe Size: {len(base_universe)}")
        print(f"Shortlist: {candidate_tickers}")
        print(f"Ticker: {ticker}")
        print(f"Headlines: {headlines}")
        print(f"Sentiment: {sentiment}")
        print(f"Regime: {regime}")
        print(f"Decision: {decision}")
        print(f"Explanation: {explanation}")
        print(f"Trade Status: {trade_status}")
        print("===============================")

        return {
            "ticker": ticker,
            "universe_size": len(base_universe),
            "shortlist": candidate_tickers,
            "headlines": headlines,
            "sentiment": sentiment,
            "regime": regime,
            "decision": decision,
            "explanation": explanation,
            "trade_status": trade_status,
        }

    except Exception as e:
        error_payload = {
            "ticker": "",
            "error": str(e)[:200],
            "trade_status": trade_status,
        }
        print("===== AI TRADE CYCLE DEBUG =====")
        print(f"Error: {error_payload['error']}")
        print(f"Trade Status: {trade_status}")
        print("===============================")
        return error_payload


def generate_trade_explanation(
    ticker: str,
    action: str,
    sentiment: Dict,
    regime: Dict,
    headlines: List[str],
) -> str:
    """Generate a 2-3 line trade explanation using Gemini, with a deterministic fallback."""
    fallback = (
        f"Action: {action}\n"
        f"Sentiment: {sentiment.get('label', 'neutral')} ({sentiment.get('score', 0.0):.2f})\n"
        f"Regime: {regime.get('regime', 'neutral')} ({regime.get('confidence', 0.0):.2f})"
    )

    try:
        client = get_gemini_client()
        if client is None:
            return fallback

        model_name = select_gemini_model(client)
        if not model_name:
            return fallback

        headlines_text = "\n".join(f"- {headline}" for headline in headlines[:5]) or "- No relevant headlines"
        prompt = (
            "Give 2-3 short lines explaining this trade decision. "
            "Use plain language and no markdown bullets.\n\n"
            f"Ticker: {ticker}\n"
            f"Action: {action}\n"
            f"Sentiment: {sentiment}\n"
            f"Regime: {regime}\n"
            f"Latest news:\n{headlines_text}"
        )
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        text = (response.text or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return fallback

        two_to_three_lines = "\n".join(lines[:3])
        return two_to_three_lines[:600]
    except Exception as e:
        logger.warning(f"Gemini explanation fallback for {ticker}: {e}")
        return fallback


class TradingScheduler:
    """Scheduler for automated trading tasks."""
    
    def __init__(self):
        self.scheduler = BackgroundScheduler(
            job_defaults={
                # Run each missed interval separately after wake/recovery.
                "coalesce": False,
                "max_instances": 1,
                # Allow missed runs to execute after long standby periods.
                "misfire_grace_time": 24 * 60 * 60,
            }
        )
        self.jobs: List[str] = []
    
    def add_job(
        self,
        func: Callable,
        trigger: str = "cron",
        job_id: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Add a scheduled job.
        
        Args:
            func: Function to execute
            trigger: Trigger type (e.g., "cron", "interval")
            job_id: Unique job ID
            **kwargs: Trigger arguments (e.g., hour=9, minute=30 for cron)
        
        Returns:
            Job ID
        """
        try:
            job = self.scheduler.add_job(
                func,
                kwargs.get("trigger_type", trigger),
                id=job_id,
                **{k: v for k, v in kwargs.items() if k != "trigger_type"}
            )
            self.jobs.append(job.id)
            logger.info(f"Added job {job.id}")
            return job.id
        except Exception as e:
            logger.error(f"Error adding job: {e}")
            return ""
    
    def add_cron_job(
        self,
        func: Callable,
        hour: int,
        minute: int,
        job_id: Optional[str] = None
    ) -> str:
        """
        Add a cron-scheduled job.
        
        Args:
            func: Function to execute
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
            job_id: Unique job ID
        
        Returns:
            Job ID
        """
        return self.add_job(
            func,
            trigger="cron",
            job_id=job_id,
            hour=hour,
            minute=minute
        )
    
    def add_interval_job(
        self,
        func: Callable,
        minutes: int = 1,
        job_id: Optional[str] = None
    ) -> str:
        """
        Add an interval-scheduled job.
        
        Args:
            func: Function to execute
            minutes: Interval in minutes
            job_id: Unique job ID
        
        Returns:
            Job ID
        """
        return self.add_job(
            func,
            trigger="interval",
            job_id=job_id,
            minutes=minutes
        )
    
    def start(self):
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Trading scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Trading scheduler stopped")
    
    def get_jobs(self) -> List[str]:
        """Get all scheduled job IDs."""
        return self.jobs
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        try:
            self.scheduler.remove_job(job_id)
            self.jobs.remove(job_id)
            logger.info(f"Removed job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing job: {e}")
            return False


def run_trading_cycle(ticker: str = "AAPL") -> Dict:
    """
    Execute a complete trading cycle: fetch news, sentiment, HMM, decision, execute.
    
    Args:
        ticker: Stock ticker to trade (default: AAPL)
    
    Returns:
        dict with cycle results (sentiment, regime, decision, execution)
    """
    try:
        cycle_start = datetime.now()
        logger.info(f"Starting trading cycle for {ticker}")
        
        results = {
            "ticker": ticker,
            "timestamp": cycle_start.isoformat(),
            "status": "started"
        }
        
        # Step 1 & 2: Fetch news
        try:
            news = get_news(ticker, limit=10)
            logger.info(f"Fetched {len(news)} news items for {ticker}")
            results["news_count"] = len(news)
        except Exception as e:
            logger.error(f"News fetch error: {e}")
            news = []
            results["news_error"] = str(e)[:100]
        
        # Step 3: Run sentiment analysis
        try:
            sentiment = analyze_sentiment(news) if news else {"score": 0.0, "label": "neutral", "summary": "No news"}
            logger.info(f"Sentiment analysis: {sentiment['label']} ({sentiment['score']:.2f})")
            results["sentiment"] = sentiment
        except Exception as e:
            logger.error(f"Sentiment error: {e}")
            sentiment = {"score": 0.0, "label": "neutral", "summary": "Error"}
            results["sentiment_error"] = str(e)[:100]
            results["sentiment"] = sentiment
        
        # Step 4: Fetch price history
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            if hist.empty:
                raise ValueError(f"No historical data for {ticker}")
            prices = hist["Close"].values.tolist()
            logger.info(f"Fetched {len(prices)} price points for {ticker}")
            results["price_points"] = len(prices)
        except Exception as e:
            logger.error(f"Price history error: {e}")
            prices = []
            results["price_error"] = str(e)[:100]
        
        # Step 5: Run HMM for market regime
        try:
            regime = get_market_regime(prices) if prices else {"regime": "neutral", "confidence": 0.0}
            logger.info(f"Market regime: {regime['regime']} ({regime['confidence']:.2f})")
            results["regime"] = regime
        except Exception as e:
            logger.error(f"HMM error: {e}")
            regime = {"regime": "neutral", "confidence": 0.0}
            results["regime_error"] = str(e)[:100]
            results["regime"] = regime
        
        # Step 6: Generate trade decision
        try:
            decision = generate_trade_decision(sentiment, regime)
            logger.info(f"Trade decision: {decision['action']} ({decision['confidence']:.2f}) - {decision['reason']}")
            results["decision"] = decision
        except Exception as e:
            logger.error(f"Decision error: {e}")
            decision = {"action": "HOLD", "confidence": 0.0, "reason": "Error"}
            results["decision_error"] = str(e)[:100]
            results["decision"] = decision

        # Generate explanation right after decision using headlines/sentiment/regime/action.
        explanation = generate_trade_explanation(
            ticker=ticker,
            action=decision.get("action", "HOLD"),
            sentiment=sentiment,
            regime=regime,
            headlines=news,
        )
        results["trade_explanation"] = explanation

        qty_for_log = 0
        if decision.get("action") != "HOLD":
            qty_for_log = max(1, int(decision.get("capital_allocation", 0.2) * 100))

        # Add explanation to trade log for traceability, regardless of execution.
        log_trade({
            "ticker": ticker,
            "sentiment": sentiment,
            "regime": regime,
            "decision": decision,
            "action": decision.get("action", "HOLD"),
            "quantity": qty_for_log,
            "explanation": explanation,
        })
        
        # Step 7: Execute trade if not HOLD
        try:
            if decision["action"] != "HOLD":
                qty = max(1, int(decision.get("capital_allocation", 0.2) * 100))  # Convert % to qty
                execution = place_trade(ticker, decision["action"], qty)
                logger.info(f"Trade executed: {execution}")
                results["execution"] = execution
                results["trade_executed"] = True
            else:
                results["trade_executed"] = False
                logger.info("No trade executed (HOLD action)")
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            results["execution_error"] = str(e)[:100]
            results["trade_executed"] = False
        
        # Summary log
        cycle_end = datetime.now()
        duration = (cycle_end - cycle_start).total_seconds()
        results["duration_seconds"] = duration
        results["status"] = "completed"
        
        logger.info(
            f"Trading cycle complete: {ticker} | "
            f"Sentiment: {sentiment.get('label')} | "
            f"Regime: {regime.get('regime')} | "
            f"Decision: {decision.get('action')} | "
            f"Duration: {duration:.2f}s"
        )
        
        return results
    
    except Exception as e:
        logger.error(f"Unexpected trading cycle error: {e}")
        return {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "error": str(e)[:200]
        }


# Global state for daily trading cycle tracking
_trading_cycle_state = _load_state()


def _is_nyse_market_open(now_et: datetime) -> bool:
    """Return True when current ET time is within regular NYSE market hours (Mon-Fri, 9:30-16:00)."""
    if now_et.weekday() >= 5:
        return False
    current_time = now_et.time()
    return NYSE_OPEN <= current_time <= NYSE_CLOSE


def reset_trading_cycle_count(hour_bucket: str):
    """Reset per-hour trading cycle execution counter."""
    _trading_cycle_state["hour_bucket"] = hour_bucket
    _trading_cycle_state["executions"] = 0
    _save_state(_trading_cycle_state)


def _trading_cycle_wrapper():
    """Run trade cycle up to 6 times per ET hour while NYSE is open."""
    now_et = datetime.now(NYSE_TZ)
    if not _is_nyse_market_open(now_et):
        logger.info("Skipping cycle: NYSE market is closed")
        return

    hour_bucket = now_et.strftime("%Y-%m-%d %H")
    if _trading_cycle_state.get("hour_bucket") != hour_bucket:
        reset_trading_cycle_count(hour_bucket)

    if _trading_cycle_state["executions"] >= _trading_cycle_state["max_per_hour"]:
        logger.info(
            f"Hourly cycle limit reached: {_trading_cycle_state['executions']}/{_trading_cycle_state['max_per_hour']}"
        )
        return
    
    # Run one AI trading cycle
    try:
        run_ai_trade_cycle()
        _trading_cycle_state["executions"] += 1
        _save_state(_trading_cycle_state)
        logger.info(
            f"AI cycle execution {_trading_cycle_state['executions']}/{_trading_cycle_state['max_per_hour']} for {hour_bucket} ET"
        )
    except Exception as e:
        logger.error(f"AI cycle wrapper error: {e}")


def schedule_trading_cycles(scheduler: TradingScheduler, interval_minutes: int = 10) -> str:
    """
    Schedule trading cycles to run at regular intervals.
    
    Args:
        scheduler: TradingScheduler instance
        interval_minutes: Interval between execution attempts in minutes (default: 10)
    
    Returns:
        Job ID
    """
    job_id = f"trading_cycle_{interval_minutes}m"
    
    try:
        job_id = scheduler.add_interval_job(
            _trading_cycle_wrapper,
            minutes=interval_minutes,
            job_id=job_id
        )
        logger.info(f"Scheduled trading cycle checks every {interval_minutes} minutes")
        return job_id
    except Exception as e:
        logger.error(f"Error scheduling trading cycles: {e}")
        return ""


# Global scheduler instance
_scheduler: Optional[TradingScheduler] = None


def get_scheduler() -> TradingScheduler:
    """Get or create global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TradingScheduler()
    return _scheduler


def start_trading_scheduler() -> TradingScheduler:
    """
    Start the global trading scheduler with trading cycles.
    
    Automatically schedules cycle checks every 10 minutes, and executes
    up to 6 cycles per ET hour during regular NYSE market hours.
    """
    scheduler = get_scheduler()
    
    # Schedule trading cycle checks every 10 minutes.
    try:
        existing_jobs = scheduler.get_jobs()
        if "trading_cycle_10m" not in existing_jobs:
            schedule_trading_cycles(scheduler, interval_minutes=10)
            logger.info("Trading cycles scheduled: 6/hour during NYSE open hours")
    except Exception as e:
        logger.error(f"Error scheduling cycles in start_trading_scheduler: {e}")

    # Start the scheduler
    scheduler.start()
    logger.info("Trading scheduler started with automated cycles")
    return scheduler


def stop_trading_scheduler():
    """Stop the global trading scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None
