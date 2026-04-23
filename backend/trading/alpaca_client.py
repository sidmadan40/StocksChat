"""Alpaca trading API client wrapper."""

from typing import Dict, List, Optional
import re
import alpaca_trade_api as tradeapi

from backend.config import APCA_API_BASE_URL, APCA_API_KEY_ID, APCA_API_SECRET_KEY


def _redact_sensitive_text(text: str) -> str:
    """Redact likely credential values from loggable text."""
    redacted = text or ""
    for value in (APCA_API_KEY_ID, APCA_API_SECRET_KEY):
        if value:
            redacted = redacted.replace(value, "***REDACTED***")

    # Generic key=value leakage forms.
    redacted = re.sub(r"(APCA_API_KEY_ID\s*=\s*)[^\s,;]+", r"\1***REDACTED***", redacted)
    redacted = re.sub(r"(APCA_API_SECRET_KEY\s*=\s*)[^\s,;]+", r"\1***REDACTED***", redacted)
    return redacted


class AlpacaClient:
    """Wrapper for Alpaca Trading API."""
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        """
        Initialize Alpaca client.
        
        Args:
            api_key: Alpaca API key (default: APCA_API_KEY_ID env var)
            secret_key: Alpaca secret key (default: APCA_API_SECRET_KEY env var)
        """
        self.api_key = api_key or APCA_API_KEY_ID
        self.secret_key = secret_key or APCA_API_SECRET_KEY
        # Alpaca SDK appends /v2 for api_version="v2"; strip any user-provided trailing /v2.
        self.base_url = (APCA_API_BASE_URL or "").rstrip("/")
        if self.base_url.endswith("/v2"):
            self.base_url = self.base_url[:-3]
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API keys not configured. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY.")
        
        self.client = tradeapi.REST(
            key_id=self.api_key,
            secret_key=self.secret_key,
            base_url=self.base_url,
            api_version="v2"
        )

    def _format_api_error(self, error: Exception) -> Dict:
        """Return a consistent error payload with invalid-key detection."""
        message = _redact_sensitive_text(str(error))[:200]
        lowered = message.lower()
        if any(term in lowered for term in ["forbidden", "unauthorized", "invalid", "authentication", "not authenticated"]):
            return {
                "status": "error",
                "error": "Invalid Alpaca API credentials or base URL.",
                "details": message
            }
        return {
            "status": "error",
            "error": message
        }

    def test_connection(self) -> Dict:
        """Test the Alpaca REST connection using the configured credentials."""
        try:
            account = self.client.get_account()
            return {
                "status": "success",
                "account_id": str(account.id),
                "account_status": str(account.status),
                "base_url": self.base_url,
            }
        except Exception as e:
            return self._format_api_error(e)
    
    def get_account(self) -> Dict:
        """Get account information."""
        try:
            account = self.client.get_account()
            return {
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
                "buying_power": float(account.buying_power),
                "status": str(account.status)
            }
        except Exception as e:
            return self._format_api_error(e)
    
    def get_positions(self) -> List[Dict]:
        """Get current positions."""
        try:
            positions = self.client.get_all_positions()
            return [
                {
                    "symbol": pos.symbol,
                    "qty": float(pos.qty),
                    "avg_fill_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "market_value": float(pos.market_value),
                    "unrealized_pl": float(pos.unrealized_pl),
                    "unrealized_plpc": float(pos.unrealized_plpc)
                }
                for pos in positions
            ]
        except Exception as e:
            return [self._format_api_error(e)]
    
    def buy(self, symbol: str, qty: int) -> Dict:
        """Place a buy market order."""
        try:
            order = self.client.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day"
            )
            return {
                "status": "success",
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty),
                "side": str(order.side)
            }
        except Exception as e:
            return self._format_api_error(e)
    
    def sell(self, symbol: str, qty: int) -> Dict:
        """Place a sell market order."""
        try:
            order = self.client.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day"
            )
            return {
                "status": "success",
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty),
                "side": str(order.side)
            }
        except Exception as e:
            return self._format_api_error(e)
    
    def place_trade(self, ticker: str, action: str, qty: int) -> Dict:
        """
        Place a trade (BUY or SELL).
        
        Args:
            ticker: Stock ticker symbol
            action: "BUY" or "SELL"
            qty: Quantity to trade
        
        Returns:
            dict with order status, id, and details
        """
        try:
            action = action.upper()
            
            if action not in ["BUY", "SELL"]:
                return {"status": "error", "error": "Action must be BUY or SELL"}
            
            if qty <= 0:
                return {"status": "error", "error": "Quantity must be positive"}
            
            # Use existing buy/sell methods
            if action == "BUY":
                result = self.buy(ticker, int(qty))
            else:
                result = self.sell(ticker, int(qty))
            
            return result
        
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}
    
    def get_portfolio(self) -> Dict:
        """
        Get current portfolio with cash, positions, and PnL.
        
        Returns:
            dict with:
            - cash: float (available cash)
            - total_portfolio_value: float
            - positions: list of {ticker, qty, pnl}
            - total_pnl: float
        """
        try:
            account = self.get_account()
            positions_raw = self.get_positions()
            
            # Handle errors
            if "error" in account:
                return {"error": f"Account error: {account['error']}"}
            
            if positions_raw and "error" in positions_raw[0]:
                positions_raw = []
            
            # Structure positions
            positions = []
            total_pnl = 0.0
            
            for pos in positions_raw:
                if "error" in pos:
                    continue
                
                pnl = float(pos.get("unrealized_pl", 0.0))
                total_pnl += pnl
                
                positions.append({
                    "ticker": pos["symbol"],
                    "qty": pos["qty"],
                    "avg_fill_price": float(pos.get("avg_fill_price", 0.0)),
                    "current_price": float(pos.get("current_price", 0.0)),
                    "pnl": pnl,
                    "pnl_percent": float(pos.get("unrealized_plpc", 0.0)) * 100
                })
            
            portfolio_value = float(account.get("portfolio_value", 0.0) or 0.0)
            cash = float(account.get("cash", 0.0) or 0.0)
            invested_value = portfolio_value - cash

            return {
                "cash": cash,
                "total_portfolio_value": portfolio_value,
                "buying_power": account.get("buying_power", 0.0),
                "positions": positions,
                "total_pnl": total_pnl,
                "total_pnl_percent": (total_pnl / invested_value) * 100 if invested_value > 0 else 0.0
            }
        
        except Exception as e:
            return {"error": str(e)[:200]}



def get_alpaca_positions() -> List[Dict]:
    """
    Get Alpaca positions without initializing client explicitly.
    For convenience in other modules.
    """
    try:
        client = AlpacaClient()
        return client.get_positions()
    except Exception as e:
        return [{"error": str(e)}]


def test_alpaca_connection() -> Dict:
    """Convenience wrapper to test Alpaca credentials and connectivity."""
    try:
        client = AlpacaClient()
        result = client.test_connection()
        if result.get("status") == "success":
            print(
                "[Alpaca] SUCCESS: "
                f"account_id={result.get('account_id')} "
                f"status={result.get('account_status')} "
                f"base_url={result.get('base_url')}"
            )
        else:
            print(f"[Alpaca] FAILED: {result.get('error', 'Unknown error')}")
        return result
    except Exception as e:
        message = _redact_sensitive_text(str(e))[:200]
        result = {
            "status": "error",
            "error": message
        }
        print(f"[Alpaca] FAILED: {message}")
        return result


def place_trade(ticker: str, action: str, qty: int) -> Dict:
    """
    Place a trade via Alpaca.
    
    Args:
        ticker: Stock ticker symbol
        action: "BUY" or "SELL"
        qty: Quantity to trade
    
    Returns:
        dict with order status and details
    """
    try:
        client = AlpacaClient()
        return client.place_trade(ticker, action, qty)
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


def get_portfolio() -> Dict:
    """
    Get current Alpaca portfolio.
    
    Returns:
        dict with cash, positions, and PnL
    """
    try:
        client = AlpacaClient()
        return client.get_portfolio()
    except Exception as e:
        return {"error": str(e)[:200]}
