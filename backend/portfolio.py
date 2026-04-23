class Portfolio:
    """
    Simple in-memory portfolio system.
    """

    def __init__(self, initial_cash=10000):
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions = {}  # dict: ticker -> quantity

    def execute_trade(self, ticker, price, action):
        """
        Execute a trade.

        Args:
            ticker (str): Stock ticker
            price (float): Current stock price
            action (str): 'BUY' or 'SELL'

        Returns:
            dict: Updated portfolio {'cash': float, 'positions': dict}
        """
        action = action.upper()

        if action == 'BUY':
            # Use 10% of available cash
            invest_amount = self.cash * 0.1
            shares_to_buy = int(invest_amount // price)
            if shares_to_buy > 0:
                total_cost = shares_to_buy * price
                self.cash -= total_cost
                self.positions[ticker] = self.positions.get(ticker, 0) + shares_to_buy

        elif action == 'SELL':
            # Liquidate entire position
            if ticker in self.positions:
                shares_to_sell = self.positions[ticker]
                total_proceeds = shares_to_sell * price
                self.cash += total_proceeds
                del self.positions[ticker]

        return {
            'cash': self.cash,
            'positions': self.positions.copy()
        }

    def get_portfolio(self):
        """
        Get current portfolio state.

        Returns:
            dict: {'cash': float, 'positions': dict}
        """
        return {
            'cash': self.cash,
            'positions': self.positions.copy()
        }