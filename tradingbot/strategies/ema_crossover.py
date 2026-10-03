import pandas as pd
from tradingbot.strategies.base_strategy import BaseStrategy
from tradingbot.utils.logger import log

class EMACrossoverStrategy(BaseStrategy):
    """
    EMA Crossover Strategy:
    - Generates a BUY signal when the fast EMA crosses above the slow EMA.
    - Generates a SELL signal when the fast EMA crosses below the slow EMA.
    - Returns HOLD otherwise.
    """
    def __init__(self, fast_period: int = 9, slow_period: int = 21):
        self.fast_period = fast_period
        self.slow_period = slow_period
        log.info(f"Initialized EMACrossoverStrategy with fast={fast_period}, slow={slow_period}")

    def generate_signal(self, df: pd.DataFrame) -> str:
        """
        Analyzes a DataFrame of market data and returns a trading signal based on EMA crossovers.
        """
        if df is None or df.empty:
            log.warning("Empty or None DataFrame passed to generate_signal.")
            return "HOLD"
            
        if len(df) < self.slow_period + 1:
            log.warning(f"Not enough data to calculate EMAs for {self.slow_period} periods. Need at least {self.slow_period + 1} rows.")
            return "HOLD"

        close_col = 'close' if 'close' in df.columns else 'Close'
        if close_col not in df.columns:
            log.error(f"Close column not found in dataframe. Available columns: {list(df.columns)}")
            return "HOLD"

        # Calculate EMAs using pandas ewm natively
        fast_ema = df[close_col].ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = df[close_col].ewm(span=self.slow_period, adjust=False).mean()

        if fast_ema is None or slow_ema is None:
            log.error("EMA calculation returned None.")
            return "HOLD"

        # Get last two rows for crossover check
        curr_fast = fast_ema.iloc[-1]
        curr_slow = slow_ema.iloc[-1]
        prev_fast = fast_ema.iloc[-2]
        prev_slow = slow_ema.iloc[-2]

        if pd.isna(curr_fast) or pd.isna(curr_slow) or pd.isna(prev_fast) or pd.isna(prev_slow):
            return "HOLD"

        if curr_fast > curr_slow and prev_fast <= prev_slow:
            log.info(f"BUY signal: fast EMA ({curr_fast:.2f}) crossed above slow EMA ({curr_slow:.2f})")
            return "BUY"
        elif curr_fast < curr_slow and prev_fast >= prev_slow:
            log.info(f"SELL signal: fast EMA ({curr_fast:.2f}) crossed below slow EMA ({curr_slow:.2f})")
            return "SELL"
        else:
            return "HOLD"
