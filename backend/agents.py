import pandas as pd

def market_agent(stock_data):
    """
    Determines bullish or bearish trend based on latest price vs historical average.

    Args:
        stock_data (dict): Output from get_stock_data function

    Returns:
        str: 'bullish' or 'bearish'
    """
    hist = stock_data['historical_data']
    avg_price = hist['Close'].mean()
    latest = stock_data['latest_price']
    return 'bullish' if latest > avg_price else 'bearish'

def technical_agent(stock_data):
    """
    Calculates 50-day moving average and gives bullish/bearish signal.

    Args:
        stock_data (dict): Output from get_stock_data function

    Returns:
        str: 'bullish', 'bearish', or 'insufficient_data'
    """
    hist = stock_data['historical_data']
    if len(hist) < 50:
        return 'insufficient_data'
    ma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
    latest = stock_data['latest_price']
    return 'bullish' if latest > ma50 else 'bearish'

def sentiment_agent(stock_data):
    """
    Returns mock sentiment analysis.

    Args:
        stock_data (dict): Output from get_stock_data function

    Returns:
        str: Mock sentiment ('positive', 'negative', 'neutral')
    """
    # Mock implementation - in real app, this would analyze news/social media
    return 'neutral'

def decision_agent(stock_data):
    """
    Combines agent outputs to return BUY, SELL, HOLD with confidence.

    Args:
        stock_data (dict): Output from get_stock_data function

    Returns:
        dict: {'decision': 'BUY'/'SELL'/'HOLD', 'confidence': float, 'signals': dict}
    """
    market = market_agent(stock_data)
    tech = technical_agent(stock_data)
    sent = sentiment_agent(stock_data)

    # Simple decision logic: count bullish/bearish signals
    signals = [market, tech]  # Ignoring sentiment for now as it's mock
    bullish_count = signals.count('bullish')
    bearish_count = signals.count('bearish')

    if bullish_count == 2:
        decision = 'BUY'
        confidence = 0.8
    elif bearish_count == 2:
        decision = 'SELL'
        confidence = 0.8
    else:
        decision = 'HOLD'
        confidence = 0.5

    return {
        'decision': decision,
        'confidence': confidence,
        'signals': {
            'market': market,
            'technical': tech,
            'sentiment': sent
        }
    }