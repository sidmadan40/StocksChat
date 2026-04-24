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

        # Get news
        try:
            for article in (stock.news or [])[:3]:
                if not isinstance(article, dict):
                    continue
                content = article.get("content", {})
                news_items.append({
                    "title": content.get("title", "Untitled article"),
                    "summary": content.get("summary") or "No summary available.",
                    "link": content.get("clickThroughUrl", {}).get("url"),
                })
        except Exception as e:
            print(f"News fetch error for {ticker}: {e}")

        # Price chart - 6 months
        price_chart = None
        try:
            if not hist.empty and len(hist) > 0:
                fig = px.line(
                    hist.reset_index(),
                    x="Date",
                    y="Close",
                    title=f"{ticker} - 6 Month Price History",
                    labels={"Close": "Price ($)", "Date": "Date"}
                )
                fig.update_layout(
                    height=300,
                    paper_bgcolor="rgba(10, 15, 44, 0.5)",
                    plot_bgcolor="rgba(10, 15, 44, 0.3)",
                    font=dict(color="#facc15", size=10),
                    hovermode="x unified",
                    margin=dict(l=40, r=20, t=40, b=40)
                )
                fig.update_xaxes(gridcolor="#1e293b")
                fig.update_yaxes(gridcolor="#1e293b")
                price_chart = fig.to_json()
        except Exception as e:
            print(f"Price chart error for {ticker}: {e}")

        # Key stats
        stats_rows = []
        try:
            current_price = info.get("currentPrice", 0)
            if current_price:
                stats_rows.append({"Metric": "Current Price", "Value": f"${current_price:.2f}"})
            
            market_cap = info.get("marketCap")
            if market_cap:
                if market_cap >= 1e12:
                    stats_rows.append({"Metric": "Market Cap", "Value": f"${market_cap/1e12:.1f}T"})
                elif market_cap >= 1e9:
                    stats_rows.append({"Metric": "Market Cap", "Value": f"${market_cap/1e9:.1f}B"})
            
            pe = info.get("trailingPE")
            if pe:
                stats_rows.append({"Metric": "P/E Ratio", "Value": f"{pe:.2f}"})
            
            sector = info.get("sector")
            if sector:
                stats_rows.append({"Metric": "Sector", "Value": sector})
            
            if len(hist) > 0:
                latest = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-5] if len(hist) > 5 else hist["Close"].iloc[0]
                if prev > 0:
                    change_pct = ((latest - prev) / prev) * 100
                    stats_rows.append({"Metric": "5D Change", "Value": f"{change_pct:+.2f}%"})
        except Exception as e:
            print(f"Stats error for {ticker}: {e}")

        return price_chart, stats_rows, news_items
    except Exception as e:
        print(f"Analysis snapshot error for {ticker}: {e}")
        return None, [], []


# Track PnL history for trend line
if "pnl_history" not in st.session_state:
    st.session_state.pnl_history = []


def show_portfolio_panel():
    """Display live Alpaca portfolio with metrics, pie chart, and holdings list."""
    st.subheader("💼 Portfolio")
    
    with st.spinner("Loading portfolio..."):
        data, error = safe_api_call(PORTFOLIO_LIVE_API_URL)
    
    if error:
        st.error(f"❌ Error: {error}")
        return
    
    if not data or data.get("status") != "success":
        st.error(f"❌ Error: {data.get('error', 'Unknown error') if data else 'No data'}")
        return
    
    portfolio = data.get("data", {})
    if not portfolio:
        st.error("No portfolio data available")
        return
    
    cash = portfolio.get("cash", 0.0)
    invested_value = portfolio.get("invested_value", 0.0)
    total_portfolio_value = portfolio.get("total_portfolio_value", 0.0)
    positions = portfolio.get("positions", [])
    pnl_data = portfolio.get("pnl", {})
    total_pnl = pnl_data.get("total", 0.0)
    pnl_percent = pnl_data.get("percent", 0.0)
    
    # (1) Top metrics - reorganized
    col1, col2 = st.columns(2)
    with col1:
        st.metric("💰 Cash Reserve", f"${cash:,.0f}")
    with col2:
        st.metric("📊 Invested", f"${invested_value:,.0f}")
    
    col3, col4 = st.columns(2)
    with col3:
        st.metric("📈 Portfolio Value", f"${total_portfolio_value:,.0f}")
    with col4:
        color = "🟢" if total_pnl >= 0 else "🔴"
        st.metric(f"{color} Gain/Loss", f"${total_pnl:,.0f}", delta=f"{pnl_percent:.2f}%")
    
    st.markdown("---")
    
    # (2) Pie chart - always show, even with no positions
    try:
        labels = []
        values = []
        colors = []
        
        # Add cash
        if cash > 0:
            labels.append("Cash Reserve")
            values.append(cash)
            colors.append("#64748b")
        
        # Add positions
        for pos in positions:
            ticker = pos.get("ticker", "Unknown")
            market_value = float(pos.get("current_price", 0)) * float(pos.get("qty", 0))
            pnl = float(pos.get("pnl", 0.0))
            
            if market_value > 0:  # Only add if there's value
                labels.append(ticker)
                values.append(market_value)
                colors.append("#10b981" if pnl >= 0 else "#ef4444")
        
        # Create pie chart if we have data
        if labels and values:
            fig_pie = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors),
                textposition="inside",
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Value: $%{value:,.0f}<extra></extra>"
            )])
            fig_pie.update_layout(
                title_text="Asset Allocation",
                height=280,
                margin=dict(l=10, r=10, t=40, b=10),
                paper_bgcolor="rgba(10, 15, 44, 0.5)",
                plot_bgcolor="rgba(10, 15, 44, 0.3)",
                font=dict(color="#facc15", size=11),
                showlegend=False
            )
            st.plotly_chart(fig_pie, use_container_width=True, key=f"portfolio_pie_{datetime.now().timestamp()}")
        else:
            st.info("⚠️ No portfolio data available yet")
    except Exception as e:
        st.warning(f"Chart error: {str(e)[:100]}")
    
    st.markdown("---")
    
    # (3) Holdings list - show if there are positions
    if positions and len(positions) > 0:
        st.subheader("📋 Holdings")
        holdings_data = []
        for pos in positions:
            market_val = float(pos.get("current_price", 0)) * float(pos.get("qty", 0))
            holdings_data.append({
                "🔹 Ticker": pos.get("ticker", "N/A"),
                "Qty": f"{float(pos.get('qty', 0)):.0f}",
                "Price": f"${float(pos.get('current_price', 0)):.2f}",
                "Value": f"${market_val:,.0f}",
                "P&L": f"${float(pos.get('pnl', 0)):,.0f}",
                "Return": f"{float(pos.get('pnl_percent', 0)):.1f}%"
            })
        
        try:
            st.dataframe(holdings_data, use_container_width=True, hide_index=True)
        except Exception as e:
            st.warning(f"Table error: {str(e)[:100]}")
    else:
        st.info("📌 No open positions. Portfolio is in cash.")


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
            # Main message text
            st.markdown(message["content"])

            # Portfolio allocation chart (from analyze endpoint)
            if "chart" in message and message["chart"]:
                try:
                    fig = pio.from_json(message["chart"])
                    st.plotly_chart(fig, use_container_width=True, key=f"chart_{idx}_{datetime.now().timestamp()}")
                except Exception as e:
                    st.warning(f"Chart rendering failed: {str(e)[:100]}")

            # Stock price chart (6-month historical)
            if "price_chart" in message and message["price_chart"]:
                try:
                    fig = pio.from_json(message["price_chart"])
                    st.plotly_chart(fig, use_container_width=True, key=f"price_chart_{idx}_{datetime.now().timestamp()}")
                except Exception as e:
                    st.warning(f"Price chart rendering failed: {str(e)[:100]}")

            # Key statistics table
            if "stats_table" in message and message["stats_table"]:
                st.caption("📈 Key Statistics")
                try:
                    st.dataframe(message["stats_table"], use_container_width=True, hide_index=True)
                except Exception as e:
                    st.warning(f"Stats table rendering failed: {str(e)[:100]}")

            # News snippets
            if "news_items" in message and message["news_items"]:
                st.caption("📰 Related News")
                for article in message["news_items"]:
                    with st.expander(article.get("title", "Latest news")):
                        st.write(article.get("summary", "No summary available."))
                        link = article.get("link")
                        if link:
                            st.markdown(f"[Read full article →]({link})")

            # Reasoning trace (LangGraph steps)
            if "trace" in message and message["trace"]:
                with st.expander("🧠 Show Reasoning (LangGraph Steps)"):
                    try:
                        for step in message["trace"]:
                            step_name = step.get('step', 'Unknown')
                            st.subheader(f"📍 {step_name.title()}")
                            
                            # Input
                            if step.get('input'):
                                with st.container():
                                    st.write("**Input:**")
                                    st.json(step['input'])
                            
                            # Output
                            if step.get('output'):
                                with st.container():
                                    st.write("**Output:**")
                                    st.json(step['output'])
                            
                            st.divider()
                    except Exception as e:
                        st.warning(f"Trace rendering failed: {str(e)[:100]}")

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
            with st.spinner("Analyzing..."):
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
                msg = {
                    "role": "assistant",
                    "content": chat_data.get("response", "No response generated."),
                }
                
                # Add analysis snapshot if we found a ticker
                if resolved_ticker:
                    try:
                        price_chart, stats_rows, news_items = build_analysis_snapshot(resolved_ticker)
                        if price_chart:
                            msg["price_chart"] = price_chart
                        if stats_rows:
                            msg["stats_table"] = stats_rows
                        if news_items:
                            msg["news_items"] = news_items
                    except Exception as e:
                        print(f"Error building snapshot for {resolved_ticker}: {e}")
                
                st.session_state.messages.append(msg)

        elif intent == "portfolio":
            with st.spinner("Fetching portfolio..."):
                try:
                    res = requests.get(PORTFOLIO_API_URL, timeout=10)
                    data = res.json()
                except Exception as e:
                    data = {"status": "error", "error": str(e)}
            
            portfolio_info = data.get("portfolio", {})
            num_positions = portfolio_info.get("num_positions", 0)
            
            if num_positions > 0:
                content = f"📊 **Your Portfolio**\n\nYou currently own **{num_positions} position(s)**:\n\n"
                for pos in portfolio_info.get("positions", []):
                    ticker = pos.get("ticker", "?")
                    qty = float(pos.get("qty", 0))
                    price = float(pos.get("current_price", 0))
                    value = qty * price
                    pnl = float(pos.get("pnl", 0))
                    content += f"• **{ticker}**: {qty:.0f} shares @ ${price:.2f} = ${value:,.0f} (P&L: ${pnl:+,.0f})\n"
            else:
                content = "📊 **Your Portfolio**\n\nYour portfolio is currently **all cash** with no stock positions open. You have the buying power to start investing!"
            
            st.session_state.messages.append({
                "role": "assistant",
                "content": content,
                "chart": data.get("allocation_chart") if data.get("allocation_chart") else None
            })

        elif intent == "correlation" and len(tickers) >= 2:
            with st.spinner("Computing correlation..."):
                res = requests.post(CORRELATION_API_URL, json={"tickers": tickers})
                data = res.json()

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"📈 **Correlation Analysis: {', '.join(tickers)}**\n\nHere's the correlation heatmap showing how these stocks move together:",
                "chart": data.get("heatmap")
            })

        elif intent == "analyze" and tickers:
            ticker = tickers[0]
            with st.spinner(f"Analyzing {ticker}..."):
                res = requests.post(API_URL, json={"ticker": ticker})
                data = res.json()
                price_chart, stats_rows, news_items = build_analysis_snapshot(ticker)

            st.session_state.selected_ticker = ticker

            # Build message with all components
            msg = {
                "role": "assistant",
                "content": f"📊 **Analysis for {ticker}**\n\nDecision: **{data.get('decision', 'HOLD')}**\n\nHere's the detailed analysis including portfolio allocation, technical indicators, and reasoning.",
                "chart": data.get("portfolio_chart"),
                "price_chart": price_chart,
                "stats_table": stats_rows,
                "news_items": news_items,
                "trace": data.get("trace", [])
            }
            st.session_state.messages.append(msg)

        elif intent == "compare" and len(tickers) >= 2:
            with st.spinner(f"Comparing {', '.join(tickers)}..."):
                res = requests.post(CORRELATION_API_URL, json={"tickers": tickers})
                data = res.json()

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"📊 **Comparison: {', '.join(tickers)}**\n\nHere's a correlation analysis between these stocks:",
                "chart": data.get("heatmap")
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
                msg = {
                    "role": "assistant",
                    "content": chat_data.get("response", "No response generated."),
                }
                
                # Add analysis snapshot if we found a ticker
                if resolved_ticker:
                    try:
                        price_chart, stats_rows, news_items = build_analysis_snapshot(resolved_ticker)
                        if price_chart:
                            msg["price_chart"] = price_chart
                        if stats_rows:
                            msg["stats_table"] = stats_rows
                        if news_items:
                            msg["news_items"] = news_items
                    except Exception as e:
                        print(f"Error building snapshot for {resolved_ticker}: {e}")
                
                st.session_state.messages.append(msg)

        st.rerun()


# ---------------- RIGHT (PORTFOLIO STATS) ----------------
with right:
    st.markdown("### 💼 Portfolio")
    
    # Refresh button
    if st.button("🔄 Refresh", use_container_width=True, key="refresh_portfolio"):
        st.rerun()
    
    # Show portfolio with error handling
    try:
        show_portfolio_panel()
    except Exception as e:
        st.error(f"Portfolio error: {str(e)[:100]}")
    
    st.markdown("---")
    
    # Show latest trades
    try:
        show_latest_trades_panel()
    except Exception as e:
        st.warning(f"Trades panel error: {str(e)[:100]}")
