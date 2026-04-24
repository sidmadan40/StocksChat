import os
import sys
import types
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
import plotly.graph_objects as go
from groq import Groq
from google import genai
import yfinance as yf
from datetime import datetime
import json
from pathlib import Path

if __package__ in (None, ""):
    backend_package = types.ModuleType("backend")
    backend_package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules.setdefault("backend", backend_package)

from backend.utils import get_stock_data, get_correlation_heatmap
from backend.graph import build_stock_state_graph, create_initial_state
from backend.portfolio import Portfolio
from backend.router import route_query
from backend.trading import start_trading_scheduler, stop_trading_scheduler
from backend.trading import get_portfolio as get_alpaca_portfolio
from backend.config import validate_required_config
from backend.gemini_client import get_gemini_client, select_gemini_model

from typing import List


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle backend startup and shutdown without deprecated event hooks."""
    validate_required_config()

    try:
        start_trading_scheduler()
    except Exception as e:
        raise RuntimeError(f"Startup blocked: failed to start trading scheduler: {e}") from e

    try:
        yield
    finally:
        try:
            stop_trading_scheduler()
        except Exception as e:
            print(f"Error stopping trading scheduler: {e}")


app = FastAPI(lifespan=lifespan)

# Global in-memory portfolio
portfolio = Portfolio()

# Compile the LangGraph once for repeated /analyze requests
stock_state_graph = build_stock_state_graph()

# Trade log file path (shared with backend/trading/trade_logger.py)
TRADES_LOG_FILE = Path(__file__).parent / "data" / "trades.json"

def ensure_trades_file():
    """Ensure trades.json file exists."""
    TRADES_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TRADES_LOG_FILE.exists():
        TRADES_LOG_FILE.write_text(json.dumps([], indent=2))

def read_trades_log() -> List[dict]:
    """Read all trades from JSON file."""
    try:
        ensure_trades_file()
        with open(TRADES_LOG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading trades log: {e}")
        return []

def write_trades_log(trades: List[dict]):
    """Write trades to JSON file."""
    try:
        ensure_trades_file()
        with open(TRADES_LOG_FILE, 'w') as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        print(f"Error writing trades log: {e}")

def log_trade(
    ticker: str,
    action: str,
    qty: int,
    price: float,
    reason: str = "",
    explanation: str = ""
):
    """Log a trade to JSON file."""
    try:
        trades = read_trades_log()
        
        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "action": action,
            "qty": qty,
            "price": price,
            "reason": reason,
            "explanation": explanation
        }
        
        trades.append(trade_record)
        
        # Keep only last 50 trades
        if len(trades) > 50:
            trades = trades[-50:]
        
        write_trades_log(trades)
    except Exception as e:
        print(f"Error logging trade: {e}")

class AnalyzeRequest(BaseModel):
    ticker: str

class CorrelationRequest(BaseModel):
    tickers: List[str]

class RouteRequest(BaseModel):
    prompt: str

class ChatRequest(BaseModel):
    prompt: str

class TradelogRequest(BaseModel):
    ticker: str
    action: str  # BUY or SELL
    qty: int
    price: float
    reason: str = ""
    explanation: str = ""

@app.get("/")
def health_check():
    return {"status": "ok"}


@app.post("/route")
def route_prompt(request: RouteRequest):
    result = route_query(request.prompt)
    return result


def get_portfolio_context() -> str:
    """Get current portfolio as formatted context string."""
    try:
        data = get_alpaca_portfolio()
        if "error" in data:
            return "Portfolio data unavailable."
        
        cash = data.get("cash", 0.0)
        positions = data.get("positions", [])
        total_value = data.get("total_portfolio_value", 0.0)
        total_pnl = data.get("total_pnl", 0.0)
        
        context = f"Portfolio Summary:\n"
        context += f"- Cash Available: ${cash:,.2f}\n"
        context += f"- Total Portfolio Value: ${total_value:,.2f}\n"
        context += f"- Total P&L: ${total_pnl:,.2f}\n"
        
        if positions:
            context += "\nOpen Positions:\n"
            for pos in positions:
                ticker = pos.get("ticker", "Unknown")
                qty = pos.get("qty", 0)
                price = pos.get("current_price", 0)
                pnl = pos.get("pnl", 0)
                pnl_pct = pos.get("pnl_percent", 0)
                context += f"  - {ticker}: {qty:.0f} shares @ ${price:.2f} (P&L: ${pnl:.2f}, {pnl_pct:.2f}%)\n"
        else:
            context += "\nNo open positions.\n"
        
        return context
    except Exception as e:
        return f"Error fetching portfolio: {str(e)[:100]}"


def get_recent_trades_context() -> str:
    """Get recent trade history as context."""
    try:
        trades = read_trades_log()
        
        if not trades:
            return "No recent trades."
        
        context = "Recent Trades (last 10):\n"
        for trade in trades[-10:]:  # Show last 10
            timestamp = trade.get('timestamp', '')
            # Parse ISO timestamp and format nicely
            try:
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = timestamp
            
            ticker = trade.get('ticker', 'UNKNOWN')
            action = trade.get('action', '?')
            qty = trade.get('quantity', trade.get('qty', 0))
            decision = trade.get('decision', {}) if isinstance(trade.get('decision', {}), dict) else {}
            reason = trade.get('reason', decision.get('reason', ''))
            confidence = decision.get('confidence')
            sentiment = trade.get('sentiment', {}) if isinstance(trade.get('sentiment', {}), dict) else {}
            regime = trade.get('regime', {}) if isinstance(trade.get('regime', {}), dict) else {}
            explanation = trade.get('explanation', '')
            
            context += f"  - {time_str}: {action} {qty} {ticker}"
            if reason:
                context += f" ({reason})"
            if confidence is not None:
                context += f" | confidence={confidence:.2f}"
            context += "\n"
            if sentiment:
                context += (
                    f"    Sentiment: {sentiment.get('label', 'neutral')} "
                    f"({sentiment.get('score', 0.0):.2f})\n"
                )
            if regime:
                context += (
                    f"    Regime: {regime.get('regime', 'neutral')} "
                    f"({regime.get('confidence', 0.0):.2f})\n"
                )
            if explanation:
                context += f"    Explanation: {explanation}\n"
        
        return context
    except Exception as e:
        return f"Error fetching trades: {str(e)[:100]}"


def get_market_news_context(tickers: List[str] = None) -> str:
    """Get latest news for portfolio holdings or specified tickers."""
    try:
        if not tickers:
            # Get from portfolio
            portfolio_data = get_alpaca_portfolio()
            if "error" not in portfolio_data:
                positions = portfolio_data.get("positions", [])
                tickers = [pos.get("ticker") for pos in positions]
        
        if not tickers:
            return "No tickers to fetch news for."
        
        context = "Latest Market News:\n"
        for ticker in tickers[:3]:  # Limit to 3 tickers
            try:
                stock = yf.Ticker(ticker)
                news = (stock.news or [])[:2]
                if news:
                    context += f"\n{ticker}:\n"
                    for article in news:
                        if isinstance(article, dict):
                            content = article.get("content", {})
                            title = content.get("title", "No title")
                            context += f"  - {title}\n"
            except Exception as e:
                context += f"  {ticker}: Could not fetch news\n"
        
        return context
    except Exception as e:
        return f"Error fetching news: {str(e)[:100]}"


@app.post("/chat")
def general_chat(request: ChatRequest):
    """
    Enhanced chat endpoint using Gemini API with portfolio context.
    Supports queries like:
    - "Why did we buy AAPL?"
    - "What is my portfolio performance?"
    - "Market outlook today"
    """
    try:
        # Gather context
        portfolio_context = get_portfolio_context()
        trades_context = get_recent_trades_context()
        news_context = get_market_news_context()
        
        # Build system prompt with context
        system_prompt = f"""You are an expert financial advisor for a stock trading portfolio.
    Answer questions about portfolio performance, trading decisions, and market outlook.
    Be concise and professional. Use the provided portfolio data to inform your answers.
    When the user asks why a trade was bought, sold, or held, explain the answer from the algorithm's logged decision, sentiment, regime, confidence, and explanation fields rather than using generic market trivia.
    If the trade history contains the ticker being asked about, prefer that logged trade context.

{portfolio_context}

{trades_context}

{news_context}

Guidelines:
- If asked about past trades, reference the trade history above
- If asked about portfolio performance, use actual P&L and position data
- Provide market insights based on current holdings
- Be specific with numbers from the portfolio context
- If the answer depends on a specific ticker, cite the logged action, reason, sentiment, regime, and explanation in plain English"""
        
        client = get_gemini_client()
        if client is None:
            return {"response": "⚠️ GEMINI_API_KEY not configured. Please set it in .env and restart."}

        model_name = select_gemini_model(client)
        if not model_name:
            return {"response": "⚠️ No Gemini models available for this API key."}

        response = client.models.generate_content(
            model=model_name,
            contents=f"{system_prompt}\n\nUser Query: {request.prompt}",
        )
        return {"response": (response.text or "").strip() or "No response generated."}
    
    except Exception as e:
        return {"response": f"I encountered an error: {str(e)[:200]}"}

@app.post("/analyze")
def analyze_stock(request: AnalyzeRequest):
    try:
        ticker = request.ticker
        state = create_initial_state(ticker)
        final_state = stock_state_graph.invoke(state)

        current_portfolio = final_state.get('portfolio', {'cash': 10000.0, 'positions': {}})
        labels = ['Cash']
        values = [current_portfolio.get('cash', 0.0)]

        for tick, qty in current_portfolio.get('positions', {}).items():
            try:
                current_data = get_stock_data(tick)
                current_price = current_data.get('latest_price', 0)
                value = qty * current_price
                labels.append(tick)
                values.append(value)
            except Exception as e:
                # Skip positions that fail to fetch
                print(f"Failed to fetch data for {tick}: {e}")
                continue

        fig = go.Figure(data=[go.Pie(labels=labels, values=values, title="Portfolio Allocation")])
        chart_json = fig.to_json()

        decision_data = final_state.get('decision', {})
        return {
            "decision": decision_data.get('decision', 'HOLD'),
            "agent_outputs": decision_data.get('signals', {'market': 'neutral', 'technical': 'neutral', 'sentiment': 'neutral'}),
            "portfolio": current_portfolio,
            "portfolio_chart": chart_json,
            "trace": final_state.get('trace', [])
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "error": str(e),
            "decision": "HOLD",
            "agent_outputs": {'market': 'neutral', 'technical': 'neutral', 'sentiment': 'neutral'},
            "portfolio": {'cash': 10000.0, 'positions': {}},
            "portfolio_chart": go.Figure().to_json(),
            "trace": []
        }

def build_allocation_chart(current_portfolio):
    labels = ['Cash']
    values = [current_portfolio['cash']]

    for tick, qty in current_portfolio['positions'].items():
        current_data = get_stock_data(tick)
        current_price = current_data['latest_price']
        value = qty * current_price
        labels.append(tick)
        values.append(value)

    fig = go.Figure(data=[go.Pie(labels=labels, values=values, title="Portfolio Allocation")])
    return fig.to_json()

@app.post("/correlation")
def get_correlation(request: CorrelationRequest):
    heatmap_json = get_correlation_heatmap(request.tickers)
    return {"heatmap": heatmap_json}

@app.get("/portfolio")
def get_portfolio():
    """Get portfolio with allocation chart (uses live Alpaca data)."""
    try:
        portfolio_data = get_alpaca_portfolio()
        
        if "error" in portfolio_data:
            raise RuntimeError(portfolio_data["error"])
        
        cash = float(portfolio_data.get("cash", 0.0))
        positions = portfolio_data.get("positions", [])
        total_pnl = float(portfolio_data.get("total_pnl", 0.0))
        
        # Build allocation chart
        labels = []
        values = []
        
        if cash > 0:
            labels.append("Cash")
            values.append(cash)
        
        for pos in positions:
            ticker = pos.get("ticker", "Unknown")
            market_value = float(pos.get("current_price", 0)) * float(pos.get("qty", 0))
            if market_value > 0:
                labels.append(ticker)
                values.append(market_value)
        
        # Create pie chart
        if labels and values:
            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                textposition="inside",
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Value: $%{value:,.0f}<extra></extra>"
            )])
            fig.update_layout(
                title_text="Portfolio Allocation",
                height=350,
                margin=dict(l=20, r=20, t=50, b=20),
                paper_bgcolor="rgba(10, 15, 44, 0.5)",
                plot_bgcolor="rgba(10, 15, 44, 0.3)",
                font=dict(color="#facc15", size=12),
                showlegend=True
            )
            allocation_chart = fig.to_json()
        else:
            allocation_chart = None
        
        return {
            "status": "success",
            "portfolio": {
                "cash": cash,
                "positions": positions,
                "total_pnl": total_pnl,
                "num_positions": len(positions)
            },
            "allocation_chart": allocation_chart
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:200],
            "portfolio": {"cash": 0.0, "positions": [], "total_pnl": 0.0, "num_positions": 0},
            "allocation_chart": None
        }

@app.get("/allocation")
def get_allocation():
    current_portfolio = portfolio.get_portfolio()
    allocation_chart = build_allocation_chart(current_portfolio)
    return {"allocation_chart": allocation_chart}

@app.get("/portfolio_live")
def portfolio_live():
    """
    Get live Alpaca portfolio data.
    
    Returns Alpaca account information including:
    - cash
    - positions
    - pnl (total + percent)
    - total_portfolio_value (from Alpaca account)
    - invested_value (calculated from positions)
    """
    try:
        portfolio_data = get_alpaca_portfolio()

        if "error" in portfolio_data:
            raise RuntimeError(portfolio_data["error"])

        cash = float(portfolio_data.get("cash", 0.0))
        total_portfolio_value = float(portfolio_data.get("total_portfolio_value", 0.0))
        positions = portfolio_data.get("positions", [])
        
        # Calculate invested amount from positions
        invested_value = 0.0
        for pos in positions:
            invested_value += float(pos.get("current_price", 0.0)) * float(pos.get("qty", 0.0))
        
        total_pnl = float(portfolio_data.get("total_pnl", 0.0))
        total_pnl_percent = float(portfolio_data.get("total_pnl_percent", 0.0))

        return {
            "status": "success",
            "data": {
                "cash": cash,
                "invested_value": invested_value,
                "total_portfolio_value": total_portfolio_value,
                "positions": positions,
                "pnl": {
                    "total": total_pnl,
                    "percent": total_pnl_percent,
                },
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:200],
            "data": {
                "cash": 0.0,
                "invested_value": 0.0,
                "total_portfolio_value": 0.0,
                "positions": [],
                "pnl": {
                    "total": 0.0,
                    "percent": 0.0,
                },
            }
        }

@app.post("/log_trade")
def log_trade_endpoint(request: TradelogRequest):
    """
    Log a trade to JSON file for query context.
    Called by trading scheduler when executing trades.
    """
    try:
        log_trade(
            ticker=request.ticker,
            action=request.action,
            qty=request.qty,
            price=request.price,
            reason=request.reason,
            explanation=request.explanation
        )
        return {
            "status": "success",
            "message": f"Logged {request.action} {request.qty} {request.ticker}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:200]
        }

@app.get("/trades")
def get_all_trades():
    """
    Get all trades from JSON log file.
    Returns list of all recorded trades.
    """
    try:
        trades = read_trades_log()
        return {
            "status": "success",
            "count": len(trades),
            "trades": trades
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:200],
            "trades": []
        }

@app.get("/trades/recent")
def get_recent_trades(limit: int = 10):
    """
    Get recent trades from JSON log file.
    
    Args:
        limit: Number of recent trades to return (default 10, max 50)
    
    Returns:
        List of recent trades
    """
    try:
        limit = min(max(1, limit), 50)  # Clamp between 1 and 50
        trades = read_trades_log()
        recent = trades[-limit:] if trades else []
        
        return {
            "status": "success",
            "count": len(recent),
            "trades": recent
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:200],
            "trades": []
        }

@app.get("/pnl")
def get_pnl():
    current_portfolio = portfolio.get_portfolio()
    total_position_value = 0.0
    positions_detail = {}

    for tick, qty in current_portfolio['positions'].items():
        current_data = get_stock_data(tick)
        current_price = current_data['latest_price']
        position_value = qty * current_price
        positions_detail[tick] = {
            'quantity': qty,
            'current_price': current_price,
            'value': position_value
        }
        total_position_value += position_value

    total_value = current_portfolio['cash'] + total_position_value
    pnl = total_value - portfolio.initial_cash

    return {
        "portfolio": current_portfolio,
        "positions": positions_detail,
        "total_value": total_value,
        "initial_cash": portfolio.initial_cash,
        "pnl": pnl
    }