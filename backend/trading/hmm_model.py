"""Hidden Markov Model for market state prediction."""

from typing import Dict, Tuple, Optional, List
import numpy as np
from hmmlearn import hmm
import yfinance as yf
import pandas as pd


class HMMModel:
    """HMM model for market state identification."""
    
    def __init__(self, n_states: int = 3):
        self.n_states = n_states
        self.model = hmm.GaussianHMM(n_components=n_states, covariance_type="full", n_iter=1000)
        self.is_fitted = False
    
    def fit(self, returns: np.ndarray) -> "HMMModel":
        """Fit HMM to stock returns."""
        try:
            if returns.ndim == 1:
                returns = returns.reshape(-1, 1)
            
            self.model.fit(returns)
            self.is_fitted = True
        except Exception as e:
            print(f"HMM fit error: {e}")
        
        return self
    
    def predict(self, returns: np.ndarray) -> np.ndarray:
        """Predict market states."""
        if not self.is_fitted:
            return np.zeros(len(returns))
        
        try:
            if returns.ndim == 1:
                returns = returns.reshape(-1, 1)
            return self.model.predict(returns)
        except Exception as e:
            print(f"HMM predict error: {e}")
            return np.zeros(len(returns))


def get_market_regime(prices: List[float]) -> Dict:
    """
    Determine market regime (bull/bear/neutral) using HMM.
    
    Args:
        prices: List of historical prices (at least 20 values recommended)
    
    Returns:
        dict with regime ("bull", "bear", "neutral") and confidence (0-1)
    """
    try:
        # Validate input
        if not prices or len(prices) < 3:
            return {
                "regime": "neutral",
                "confidence": 0.0
            }
        
        prices = np.array(prices, dtype=float)
        
        # Compute log returns
        log_returns = np.diff(np.log(prices))
        
        if len(log_returns) < 3:
            return {
                "regime": "neutral",
                "confidence": 0.0
            }
        
        # Reshape for HMM
        X = log_returns.reshape(-1, 1)
        
        # Fit HMM with 3 states
        model = hmm.GaussianHMM(n_components=3, covariance_type="full", n_iter=1000, random_state=42)
        model.fit(X)
        
        # Get current state (last prediction)
        states = model.predict(X)
        current_state = int(states[-1])
        
        # Get confidence from transition matrix
        transition_probs = model.transmat_[current_state]
        confidence = float(np.max(transition_probs))
        
        # Map states to regime (sorted by mean returns)
        means = np.argsort(model.means_.flatten())
        
        regime_map = {
            means[0]: "bear",      # Lowest returns
            means[1]: "neutral",   # Middle returns
            means[2]: "bull"       # Highest returns
        }
        
        regime = regime_map.get(current_state, "neutral")
        
        return {
            "regime": regime,
            "confidence": min(1.0, max(0.0, confidence))
        }
    
    except Exception as e:
        return {
            "regime": "neutral",
            "confidence": 0.0,
            "error": str(e)[:100]
        }


def fit_hmm_model(ticker: str, period: str = "1y") -> Optional[HMMModel]:
    """
    Fit HMM model to historical stock data.
    
    Args:
        ticker: Stock ticker symbol
        period: Time period for data
    
    Returns:
        Fitted HMMModel or None if error
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        
        if hist.empty:
            return None
        
        returns = hist["Close"].pct_change().dropna().values
        
        model = HMMModel(n_states=3)
        model.fit(returns)
        
        return model
    
    except Exception as e:
        print(f"HMM fit error for {ticker}: {e}")
        return None


def predict_with_hmm(model: HMMModel, ticker: str, lookback: int = 20) -> Dict:
    """
    Predict market state using fitted HMM.
    
    Args:
        model: Fitted HMMModel
        ticker: Stock ticker symbol
        lookback: Number of days to predict
    
    Returns:
        dict with predictions and confidence
    """
    try:
        if not model or not model.is_fitted:
            return {"error": "Model not fitted", "state": -1, "confidence": 0.0}
        
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        
        if hist.empty:
            return {"error": "No data", "state": -1, "confidence": 0.0}
        
        returns = hist["Close"].pct_change().dropna().values
        states = model.predict(returns[-lookback:].reshape(-1, 1))
        
        return {
            "ticker": ticker,
            "current_state": int(states[-1]),
            "states": states.tolist(),
            "confidence": float(np.max(model.model.transmat_[int(states[-1])]))
        }
    
    except Exception as e:
        return {"error": str(e), "state": -1, "confidence": 0.0}
