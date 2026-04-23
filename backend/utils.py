import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

def get_stock_data(ticker):
    """
    Fetches stock data for a given ticker using yfinance.

    Returns:
        dict: A dictionary containing:
            - 'latest_price': The latest closing price (float or None)
            - 'historical_data': Pandas DataFrame with 6 months of historical data
            - 'pe_ratio': Trailing PE ratio (float or None if not available)
    """
    stock = yf.Ticker(ticker)

    # Get latest price (last closing price)
    hist_latest = stock.history(period='1d')
    latest_price = hist_latest['Close'].iloc[-1] if not hist_latest.empty else None

    # Get historical data for 6 months
    historical_data = stock.history(period='6mo')

    # Get PE ratio if available
    info = stock.info
    pe_ratio = info.get('trailingPE', None)

    return {
        'latest_price': latest_price,
        'historical_data': historical_data,
        'pe_ratio': pe_ratio
    }

def get_correlation_heatmap(tickers, period='1y'):
    """
    Fetches historical prices for multiple tickers and returns a correlation heatmap as JSON.

    Args:
        tickers (list): List of stock tickers
        period (str): Period for historical data (default '1y')

    Returns:
        str: JSON string of Plotly heatmap figure
    """
    # Fetch historical data for each ticker
    data = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period)
            if not hist.empty:
                data[ticker] = hist['Close']
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
            continue

    if len(data) < 2:
        # Not enough data for correlation
        fig = go.Figure()
        fig.add_annotation(text="Not enough data for correlation", showarrow=False)
        return fig.to_json()

    # Create DataFrame with Close prices
    df = pd.DataFrame(data)

    # Compute correlation matrix
    corr_matrix = df.corr()

    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=corr_matrix.columns,
        y=corr_matrix.index,
        colorscale='RdBu',
        zmin=-1,
        zmax=1,
        text=corr_matrix.round(2).values,
        texttemplate='%{text}',
        textfont={"size": 10},
        hoverongaps=False
    ))

    fig.update_layout(
        title="Stock Price Correlation Heatmap",
        xaxis_title="Stocks",
        yaxis_title="Stocks"
    )

    return fig.to_json()