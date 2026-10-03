from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class ExchangeConnector(ABC):
    """
    Abstract base class defining the interface for market exchange connectors.
    """
    
    @abstractmethod
    async def fetch_balance(self) -> Dict[str, Any]:
        """Fetch the account balance."""
        pass

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch the ticker info for a given symbol."""
        pass

    @abstractmethod
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int] = None, limit: Optional[int] = None
    ) -> List[List[Any]]:
        """Fetch OHLCV (Open, High, Low, Close, Volume) data."""
        pass

    @abstractmethod
    async def create_order(
        self, symbol: str, type: str, side: str, amount: float, price: Optional[float] = None
    ) -> Dict[str, Any]:
        """Create a new trade order."""
        pass

    @abstractmethod
    async def cancel_order(self, id: str, symbol: str) -> Dict[str, Any]:
        """Cancel an existing trade order."""
        pass
        
    @abstractmethod
    async def close(self):
        """Cleanly close the connector session."""
        pass
