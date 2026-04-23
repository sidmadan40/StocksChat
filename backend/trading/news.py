"""News fetching and processing module for trading."""

from typing import List, Dict, Optional
import yfinance as yf


def get_news(ticker: str, limit: int = 5) -> List[str]:
    """
    Fetch latest news headlines for a stock using yfinance.
    
    Args:
        ticker: Stock ticker symbol
        limit: Number of headlines to fetch (default: 5, max: 10)
    
    Returns:
        List of news headlines (titles only)
    """
    try:
        # Clamp limit between 5 and 10
        limit = max(5, min(10, limit))
        
        stock = yf.Ticker(ticker)
        news = (stock.news or [])[:limit]
        
        titles = []
        for article in news:
            if not isinstance(article, dict):
                continue
            
            content = article.get("content", {})
            title = content.get("title")
            
            if title:
                titles.append(title)
        
        # Fallback if no headlines found
        if not titles:
            return [f"No recent news found for {ticker}"]
        
        return titles
    
    except Exception as e:
        return [f"Could not fetch news for {ticker}: {str(e)[:100]}"]


def fetch_latest_news(ticker: str, limit: int = 5) -> List[Dict]:
    """
    Fetch latest news for a stock using yfinance with detailed info.
    
    Args:
        ticker: Stock ticker symbol
        limit: Maximum number of news items to fetch
    
    Returns:
        List of news items with title, summary, link
    """
    try:
        stock = yf.Ticker(ticker)
        news = (stock.news or [])[:limit]
        
        processed_news = []
        for article in news:
            if not isinstance(article, dict):
                continue
            
            content = article.get("content", {})
            processed_news.append({
                "title": content.get("title", "Untitled"),
                "summary": content.get("summary", ""),
                "link": content.get("clickThroughUrl", {}).get("url"),
                "pubDate": content.get("pubDate"),
                "source": content.get("provider", {}).get("displayName")
            })
        
        return processed_news
    
    except Exception as e:
        return [{"error": str(e)}]



def filter_relevant_news(news: List[Dict], keywords: List[str]) -> List[Dict]:
    """
    Filter news items by relevant keywords.
    
    Args:
        news: List of news items
        keywords: List of keywords to filter by
    
    Returns:
        Filtered list of news items
    """
    relevant = []
    for item in news:
        if not item.get("title"):
            continue
        
        title_lower = item["title"].lower()
        if any(kw.lower() in title_lower for kw in keywords):
            relevant.append(item)
    
    return relevant
