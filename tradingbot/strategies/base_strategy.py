from abc import ABC, abstractmethod
import pandas as pd
from tradingbot.utils.logger import log

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    """

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> str:
        """
        Analyzes a DataFrame of market data and returns a trading signal.

        Args:
            df (pd.DataFrame): Market data containing OHLCV and potential indicators.

        Returns:
            str: "BUY", "SELL", or "HOLD".
        """
        pass
