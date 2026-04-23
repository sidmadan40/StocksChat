import os
import streamlit as st
import requests
import plotly.io as pio
import re
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
 

# ---------------- CONFIG ----------------
st.set_page_config(layout="wide")

# ---------------- CUSTOM CSS ----------------
st.markdown("""
<style>
    /* Background gradient */
    .main {
        background: linear-gradient(to bottom, #0a0f2c, #020617) !important;
        color: #ffffff !important;
    }
    
    /* Remove default white backgrounds */
    .stApp {
        background: linear-gradient(to bottom, #0a0f2c, #020617) !important;
    }
    
    /* Text color */
    body, .stMarkdown, .stText, .stHeader, .stSubheader, .stWrite {
        color: #ffffff !important;
    }

    .stChatMessage, .stChatMessage p, .stChatMessage div, .stChatMessage span,
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p {
        color: #ffffff !important;
    }
    
    /* Chat bubbles */
    .stChatMessage[data-testid="user"] {
        background-color: #1e293b !important; /* darker blue */
        border-radius: 10px;
        padding: 10px;
        margin: 5px 0;
    }
    
    .stChatMessage[data-testid="assistant"] {
        background-color: #334155 !important; /* slightly lighter blue */
        border-radius: 10px;
        padding: 10px;
        margin: 5px 0;
    }
    
    /* Buttons */
    .stButton > button {
        background-color: transparent !important;
        color: #facc15 !important;
        border: 2px solid #facc15 !important;
        border-radius: 20px !important;
        padding: 8px 16px !important;
        transition: all 0.3s ease !important;
    }
    
    .stButton > button:hover {
        background-color: #facc15 !important;
        color: #0a0f2c !important;
        transform: scale(1.05) !important;
    }
    
    /* Input fields */
    .stTextInput > div > div > input {
        background-color: #1e293b !important;
        color: #facc15 !important;
        border: 1px solid #facc15 !important;
        border-radius: 10px !important;
    }
    
    /* Chat input */
    .stChatInput > div > div > input {
        background-color: #1e293b !important;
        color: #ffffff !important;
        border: 1px solid #facc15 !important;
        border-radius: 10px !important;
    }
    
    /* Plotly charts background */
    .js-plotly-plot {
        background-color: #0a0f2c !important;
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background-color: #1e293b !important;
        color: #facc15 !important;
        border-radius: 10px !important;
    }
</style>
""", unsafe_allow_html=True)

_BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
API_URL = f"{_BACKEND}/analyze"
CORRELATION_API_URL = f"{_BACKEND}/correlation"
PORTFOLIO_API_URL = f"{_BACKEND}/portfolio"
PORTFOLIO_LIVE_API_URL = f"{_BACKEND}/portfolio_live"
RECENT_TRADES_API_URL = f"{_BACKEND}/trades/recent?limit=5"
ROUTE_API_URL = f"{_BACKEND}/route"
CHAT_API_URL = f"{_BACKEND}/chat"

# ---------------- STATE ----------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "page" not in st.session_state:
    st.session_state.page = "home"

if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = None

# ---------------- HELPERS ----------------
def extract_ticker(text):
    text = text.lower()

    if "s&p" in text or "sp500" in text:
        return "^GSPC"
    if "nifty" in text:
        return "^NSEI"

    matches = re.findall(r'\b[A-Z]{1,5}\b', text.upper())
    return matches[0] if matches else None


def extract_tickers(text):
    return re.findall(r'\b[A-Z]{1,5}\b', text.upper())


def safe_api_call(url, method="GET", json_data=None):
    """Safely call API and return parsed JSON, or error message"""
    try:
        if method == "POST":
            res = requests.post(url, json=json_data, timeout=10)
        else:
            res = requests.get(url, timeout=10)
        
        # Check status code
        if res.status_code != 200:
            return None, f"API Error {res.status_code}: {res.text[:200]}"
        
        # Try to parse JSON
        try:
            return res.json(), None
        except requests.exceptions.JSONDecodeError:
            return None, f"Backend returned invalid JSON. Response: {res.text[:200]}"
    
    except requests.exceptions.Timeout:
        return None, "Backend request timed out. Is the server running on port 8000?"
    except requests.exceptions.ConnectionError:
        return None, f"Cannot connect to backend on {_BACKEND}. Is it running?"
    except Exception as e:
        return None, f"API call failed: {str(e)}"


def is_trade_decision_query(prompt: str) -> bool:
    lowered = prompt.lower()
    phrases = [
        "why did we buy",
        "why did we sell",
        "why did we hold",
        "why did you buy",
        "why did you sell",
        "why did you hold",
        "trade decision",
        "recent trade",
    ]
    return any(phrase in lowered for phrase in phrases)


def resolve_query_ticker(prompt: str, routed_tickers=None):
    """Resolve a ticker from route output or recent trade/company names in the prompt."""
    routed_tickers = routed_tickers or []
    if routed_tickers:
        return routed_tickers[0]

    direct_match = extract_ticker(prompt)
    if direct_match:
        return direct_match

    trades_data, trades_error = safe_api_call(f"{_BACKEND}/trades/recent?limit=20")
    if trades_error or trades_data.get("status") != "success":
        return None

    lowered = prompt.lower()
    for trade in reversed(trades_data.get("trades", [])):
        ticker = trade.get("ticker")
        if not ticker:
            continue
        if ticker.lower() in lowered:
            return ticker

        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            info = {}

        names = [
            str(info.get("longName", "")).lower(),
            str(info.get("shortName", "")).lower(),
            str(info.get("displayName", "")).lower(),
        ]
        if any(name and name in lowered for name in names):
            return ticker

    return None


def build_analysis_snapshot(ticker: str):
    """Build chart, key stats, and recent news snippets for chat responses."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        hist = stock.history(period="6mo")
        news_items = []

        for article in (stock.news or [])[:3]:
            if not isinstance(article, dict):
                continue
            content = article.get("content", {})
            news_items.append({
                "title": content.get("title", "Untitled article"),
                "summary": content.get("summary") or "No summary available.",
                "link": content.get("clickThroughUrl", {}).get("url"),
            })

        price_chart = None
        if not hist.empty:
            fig = px.line(hist, x=hist.index, y="Close", title=f"{ticker} price over 6 months")
            fig.update_layout(
                paper_bgcolor="rgba(10, 15, 44, 0.5)",
                plot_bgcolor="rgba(10, 15, 44, 0.3)",
                font=dict(color="#facc15"),
            )
            price_chart = fig.to_json()

        stats_rows = [
            {"Metric": "Current Price", "Value": str(info.get("currentPrice", "N/A"))},
            {"Metric": "Market Cap", "Value": str(info.get("marketCap", "N/A"))},
            {"Metric": "PE Ratio", "Value": str(info.get("trailingPE", "N/A"))},
            {"Metric": "Sector", "Value": str(info.get("sector", "N/A"))},
        ]

        return price_chart, stats_rows, news_items
    except Exception:
        return None, [], []


# Track PnL history for trend line
if "pnl_history" not in st.session_state:
    st.session_state.pnl_history = []


def show_portfolio_panel():
    """Display live Alpaca portfolio with cash, positions, and PnL trend."""
    st.subheader("💼 Live Alpaca Portfolio")
    
    with st.spinner("Loading Alpaca portfolio..."):
        data, error = safe_api_call(PORTFOLIO_LIVE_API_URL)
    
    if error:
        st.error(f"❌ Portfolio Error: {error}")
        return
    
    if data["status"] != "success":
        st.error(f"❌ Portfolio Error: {data.get('error', 'Unknown error')}")
        return
    
    portfolio = data["data"]
    
    # (1) Cash and PnL metrics
    col1, col2 = st.columns(2)
    
    with col1:
        cash = portfolio.get("cash", 0.0)
        st.metric("💰 Cash", f"${cash:,.2f}")
    
    with col2:
        pnl_data = portfolio.get("pnl", {})
        total_pnl = pnl_data.get("total", 0.0)
        pnl_percent = pnl_data.get("percent", 0.0)
        color = "🟢" if total_pnl >= 0 else "🔴"
        st.metric(f"{color} P&L", f"${total_pnl:,.2f}", f"{pnl_percent:.2f}%")
    
    # Track PnL history for trend
    st.session_state.pnl_history.append({
        "timestamp": datetime.now(),
        "pnl": total_pnl
    })
    # Keep only last 50 points
    if len(st.session_state.pnl_history) > 50:
        st.session_state.pnl_history = st.session_state.pnl_history[-50:]
    
    st.markdown("---")
    
    # (2) Pie chart for allocation
    positions = portfolio.get("positions", [])
    
    if positions:
        # Build allocation data
        labels = ["💰 Cash"]
        values = [cash]
        colors = ["#64748b"]
        
        for pos in positions:
            ticker = pos.get("ticker", "Unknown")
            pnl = pos.get("pnl", 0.0)
            market_value = pos.get("current_price", 0) * pos.get("qty", 0)
            labels.append(ticker)
            values.append(market_value)
            colors.append("#10b981" if pnl >= 0 else "#ef4444")
        
        # Create pie chart
        fig_pie = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors),
            hovertemplate="<b>%{label}</b><br>Value: $%{value:.2f}<extra></extra>"
        )])
        fig_pie.update_layout(
            title="Portfolio Allocation",
            height=300,
            margin=dict(l=0, r=0, t=30, b=0),
            paper_bgcolor="rgba(10, 15, 44, 0.5)",
            font=dict(color="#facc15")
        )
        st.plotly_chart(fig_pie, width="stretch", key="portfolio_pie")
    else:
        st.info("No open positions.")
    
    st.markdown("---")
    
    # (3) PnL Trend Line
    if len(st.session_state.pnl_history) > 1:
        history_df = st.session_state.pnl_history
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(
            x=[h["timestamp"] for h in history_df],
            y=[h["pnl"] for h in history_df],
            mode="lines+markers",
            name="P&L",
            line=dict(color="#10b981", width=2),
            marker=dict(size=4)
        ))
        fig_trend.update_layout(
            title="P&L Trend",
            xaxis_title="Time",
            yaxis_title="P&L ($)",
            height=250,
            margin=dict(l=50, r=20, t=30, b=50),
            hovermode="x unified",
            paper_bgcolor="rgba(10, 15, 44, 0.5)",
            plot_bgcolor="rgba(10, 15, 44, 0.3)",
            font=dict(color="#facc15"),
            xaxis=dict(gridcolor="#1e293b"),
            yaxis=dict(gridcolor="#1e293b")
        )
        st.plotly_chart(fig_trend, width="stretch", key="pnl_trend")
    
    st.markdown("---")
    
    # (4) Positions table
    if positions:
        st.subheader("📋 Open Positions")
        position_data = []
        for pos in positions:
            position_data.append({
                "Ticker": pos.get("ticker", "N/A"),
                "Qty": f"{pos.get('qty', 0):.0f}",
                "Avg Price": f"${pos.get('avg_fill_price', 0):.2f}",
                "Current Price": f"${pos.get('current_price', 0):.2f}",
                "P&L": f"${pos.get('pnl', 0):.2f}",
                "P&L %": f"{pos.get('pnl_percent', 0):.2f}%"
            })
        
        st.dataframe(position_data, width="stretch", hide_index=True)


def show_latest_trades_panel():
    """Display latest trades from backend trades.json."""
    st.subheader("🧠 Latest Trades")

    trades_data, trades_error = safe_api_call(RECENT_TRADES_API_URL)

    if trades_error:
        st.info("Latest trades are unavailable right now.")
        return

    if trades_data.get("status") != "success" or not trades_data.get("trades"):
        st.info("No recent trades found in trades.json yet.")
        return

    trades = list(reversed(trades_data["trades"]))

    table_rows = []
    for trade in trades:
        timestamp = trade.get("timestamp", "")
        try:
            pretty_time = datetime.fromisoformat(timestamp).strftime("%b %d, %H:%M")
        except Exception:
            pretty_time = timestamp

        table_rows.append({
            "Time": pretty_time,
            "Ticker": trade.get("ticker", "-"),
            "Action": trade.get("action", "-"),
            "Qty": trade.get("qty", trade.get("quantity", "-")),
        })

    st.dataframe(table_rows, width="stretch", hide_index=True)

    for trade in trades:
        timestamp = trade.get("timestamp", "")
        try:
            pretty_time = datetime.fromisoformat(timestamp).strftime("%b %d, %H:%M")
        except Exception:
            pretty_time = timestamp

        ticker = trade.get("ticker", "Unknown")
        action = trade.get("action", "?")
        reason = trade.get("reason", "No rule-based reason stored.")
        explanation = trade.get("explanation", "No Gemini explanation stored.")

        with st.expander(f"{action} {ticker} · {pretty_time}"):
            st.write(f"**Rule Signal:** {reason}")
            st.write(f"**Explanation:** {explanation}")


# ---------------- RIGHT PANEL ----------------
def show_home_page():
    st.title("🏠 Market Overview")

    # Market selector
    market = st.selectbox("Select Market", ["US (S&P 500)", "India (NIFTY)", "UK (FTSE)"])

    # Toggle for gainers/losers
    view = st.radio("View", ["Top Gainers", "Top Losers"], horizontal=True)

    # Define stock lists
    stock_lists = {
        "US (S&P 500)": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX"],
        "India (NIFTY)": ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "HINDUNILVR.NS", "ITC.NS", "KOTAKBANK.NS"],
        "UK (FTSE)": ["ULVR.L", "HSBA.L", "BATS.L", "DGE.L", "RIO.L", "BP.L", "GSK.L", "AZN.L"]
    }

    stocks = stock_lists[market]

    # Fetch data
    with st.spinner("Fetching market data..."):
        stock_data = []
        for ticker in stocks:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                current_price = info.get("currentPrice", 0)
                previous_close = info.get("previousClose", current_price)
                if previous_close:
                    pct_change = ((current_price - previous_close) / previous_close) * 100
                else:
                    pct_change = 0
                stock_data.append({
                    "ticker": ticker,
                    "price": current_price,
                    "pct_change": pct_change
                })
            except:
                stock_data.append({
                    "ticker": ticker,
                    "price": 0,
                    "pct_change": 0
                })

    # Sort
    if view == "Top Gainers":
        stock_data.sort(key=lambda x: x["pct_change"], reverse=True)
    else:
        stock_data.sort(key=lambda x: x["pct_change"])

    # Display as cards in grid
    cols = st.columns(4)
    for i, data in enumerate(stock_data[:8]):  # Top 8
        with cols[i % 4]:
            color = "🟢" if data["pct_change"] >= 0 else "🔴"
            if st.button(f"""
{data['ticker']}
${data['price']:.2f}
{color} {data['pct_change']:.2f}%
""", key=f"{market}_{data['ticker']}"):
                st.session_state.selected_ticker = data['ticker']
                st.session_state.page = "company"
                st.rerun()


def show_company_page(ticker):
    with st.spinner("Loading company data..."):
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="6mo")

    # Back button
    if st.button("⬅ Back to Home"):
        st.session_state.page = "home"
        st.rerun()

    # Top section
    st.title(f"{info.get('longName', ticker)} ({ticker})")
    current_price = info.get('currentPrice', 'N/A')
    st.markdown(f"<h1 style='text-align: center; color: #facc15; font-size: 3em;'>{current_price}</h1>", unsafe_allow_html=True)

    st.markdown("---")  # Separator

    # Middle section: 2 columns
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Price Chart")
        fig = px.line(hist, x=hist.index, y="Close", title=f"{ticker} Price Over 6 Months")
        st.plotly_chart(fig, key=f"company_price_chart_{ticker}")

    with col2:
        st.subheader("📊 Key Stats")
        st.write(f"**PE Ratio:** {info.get('trailingPE', 'N/A')}")
        st.write(f"**Market Cap:** {info.get('marketCap', 'N/A')}")
        st.write(f"**Sector:** {info.get('sector', 'N/A')}")

    st.markdown("---")  # Separator

    # Below: Business summary
    st.subheader("🏢 Business Summary")
    summary = info.get("longBusinessSummary", "No description available.")
    st.write(summary)

    st.markdown("---")  # Separator

    # News section
    st.subheader("📰 Latest News")
    try:
        with st.spinner("Fetching news..."):
            news = (stock.news or [])[:5]
    except Exception as e:
        st.warning(f"Could not fetch news: {str(e)}")
        news = []

    if not news:
        st.info("No news available right now.")
    else:
        for article in news:
            if not isinstance(article, dict):
                continue

            # Extract from nested content structure
            content = article.get("content", {})
            title = content.get("title") or "Untitled article"
            with st.expander(title):
                st.write(content.get("summary") or "No summary available.")
                link = content.get("clickThroughUrl", {}).get("url")
                if link:
                    st.markdown(f"[Read full article]({link})")


# ---------------- LAYOUT ----------------
left, right = st.columns([2, 1])

# ---------------- LEFT (CHAT) ----------------
with left:
    st.title("💬 Stocks Portfolio Assistant")

    # Show chat history
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            if "chart" in message:
                fig = pio.from_json(message["chart"])
                st.plotly_chart(fig, key=f"chat_chart_{idx}")

            if "stats_table" in message and message["stats_table"]:
                st.dataframe(message["stats_table"], width="stretch", hide_index=True)

            if "price_chart" in message and message["price_chart"]:
                fig = pio.from_json(message["price_chart"])
                st.plotly_chart(fig, key=f"chat_price_chart_{idx}")

            if "news_items" in message and message["news_items"]:
                st.caption("Recent news snippets")
                for article in message["news_items"]:
                    with st.expander(article.get("title", "Latest news")):
                        st.write(article.get("summary", "No summary available."))
                        link = article.get("link")
                        if link:
                            st.markdown(f"[Read full article]({link})")

            if "trace" in message:
                with st.expander("Show reasoning"):
                    for step in message["trace"]:
                        st.write(f"**{step['step']}**")
                        st.write(f"Output: {step.get('output')}")
                        st.write("---")

    # Chat input
    if prompt := st.chat_input("Ask about stocks..."):
        st.session_state.messages.append({"role": "user", "content": prompt})

        # -------- LLM ROUTING --------
        with st.spinner("Thinking..."):
            route_data, route_error = safe_api_call(ROUTE_API_URL, method="POST", json_data={"prompt": prompt})
            route = route_data if not route_error else {"intent": "general", "tickers": []}

        intent = route.get("intent")
        tickers = route.get("tickers", [])
        ticker = tickers[0] if tickers else None

        if is_trade_decision_query(prompt):
            resolved_ticker = resolve_query_ticker(prompt, tickers)
            with st.spinner("Thinking..."):
                chat_data, chat_error = safe_api_call(
                    CHAT_API_URL,
                    method="POST",
                    json_data={"prompt": prompt},
                )

            if chat_error:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"⚠️ Chat service is unavailable right now: {chat_error}"
                })
            else:
                price_chart, stats_rows, news_items = build_analysis_snapshot(resolved_ticker) if resolved_ticker else (None, [], [])
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": chat_data.get("response", "No response generated."),
                    "price_chart": price_chart,
                    "stats_table": stats_rows,
                    "news_items": news_items,
                })

        elif intent == "correlation" and len(tickers) >= 2:
            with st.spinner("Computing correlation..."):
                res = requests.post(CORRELATION_API_URL, json={"tickers": tickers})
                data = res.json()

            st.session_state.messages.append({
                "role": "assistant",
                "content": "Here is the correlation analysis",
                "chart": data["heatmap"]
            })

        elif intent == "portfolio":
            with st.spinner("Fetching portfolio..."):
                res = requests.get(PORTFOLIO_API_URL)
                data = res.json()

            st.session_state.messages.append({
                "role": "assistant",
                "content": "Here is your portfolio",
                "chart": data["allocation_chart"]
            })

        elif intent == "analyze" and tickers:
            ticker = tickers[0]
            with st.spinner(f"Analyzing {ticker}..."):
                res = requests.post(API_URL, json={"ticker": ticker})
                data = res.json()
                price_chart, stats_rows, news_items = build_analysis_snapshot(ticker)

            st.session_state.selected_ticker = ticker
            st.session_state.page = "company"

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Analysis for {ticker}: decision {data.get('decision', 'HOLD')}. Here are the latest chart, key stats, reasoning trace, and recent news snippets.",
                "chart": data["portfolio_chart"],
                "price_chart": price_chart,
                "stats_table": stats_rows,
                "news_items": news_items,
                "trace": data["trace"]
            })

        elif intent == "compare" and len(tickers) >= 2:
            with st.spinner(f"Comparing {', '.join(tickers)}..."):
                res = requests.post(CORRELATION_API_URL, json={"tickers": tickers})
                data = res.json()

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Comparison between {', '.join(tickers)}",
                "chart": data["heatmap"]
            })

        else:
            resolved_ticker = resolve_query_ticker(prompt, tickers)
            with st.spinner("Thinking..."):
                chat_data, chat_error = safe_api_call(
                    CHAT_API_URL,
                    method="POST",
                    json_data={"prompt": prompt},
                )

            if chat_error:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"⚠️ Chat service is unavailable right now: {chat_error}"
                })
            else:
                price_chart, stats_rows, news_items = build_analysis_snapshot(resolved_ticker) if resolved_ticker else (None, [], [])
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": chat_data.get("response", "No response generated."),
                    "price_chart": price_chart,
                    "stats_table": stats_rows,
                    "news_items": news_items,
                })

        st.rerun()


# ---------------- RIGHT (STATS) ----------------
with right:
    refresh_col, _ = st.columns([1, 1])
    with refresh_col:
        if st.button("🔄 Refresh Position", width="stretch"):
            st.rerun()

    show_portfolio_panel()
    st.markdown("---")
    show_latest_trades_panel()
